from typing import Dict, List, Optional, Any
from datetime import datetime
import os
import json
import logging
import time

from pydantic import BaseModel, Field, ValidationError
import boto3
from botocore.exceptions import ClientError

# -------------------------
# Configuration via env vars
# -------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CHAT_TABLE_NAME = os.getenv("CHAT_TABLE_NAME", "chat-logs-table")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# Threshold (ms) to decide if close to Lambda timeout and should short-circuit
TIMEOUT_BUFFER_MS = int(os.getenv("TIMEOUT_BUFFER_MS", "300"))

# -------------------------
# Structured logging setup
# -------------------------
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        # Add extra context fields if provided
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            payload.update(record.extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger("chat_schemas_lambda")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(LOG_LEVEL)

# -------------------------
# Initialize AWS resources (cold-start optimized)
# -------------------------
# Use boto3 resource/client that will be reused across invocations
try:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    chat_table = dynamodb.Table(CHAT_TABLE_NAME)
    logger.info("DynamoDB table resource initialized", extra={"table_name": CHAT_TABLE_NAME})
except Exception as e:
    # Keep initialization safe — real error will surface on first use
    logger.error("Failed to initialize DynamoDB resource", extra={"error": str(e)})
    chat_table = None

# -------------------------
# Pydantic schema models
# (kept types consistent with original code)
# -------------------------
class ChatMessage(BaseModel):
    text: str
    context: Optional[Dict] = Field(default_factory=dict)


class ChatThreadInfo(BaseModel):
    thread_id: str
    date: datetime


class BotNessage(BaseModel):
    text: str


class ChatLog(BaseModel):
    user_message: ChatMessage
    bot_message: List[BotNessage]
    date: datetime
    context: Optional[Dict] = Field(default_factory=dict)


class ChatLogResponse(BaseModel):
    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]

# -------------------------
# Helpers
# -------------------------
def api_response(status_code: int, body: Any, headers: Optional[Dict[str, str]] = None):
    if headers is None:
        headers = {}
    # Basic CORS + content-type
    base_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    }
    base_headers.update(headers)
    return {
        "statusCode": status_code,
        "headers": base_headers,
        "body": json.dumps(body, default=str),
    }


def remaining_ms(context) -> int:
    # context can be None in local tests
    if context is None:
        return 9999999
    try:
        return context.get_remaining_time_in_millis()
    except Exception:
        return 9999999

# Convert DB item to ChatLog object (if possible)
def item_to_chatlog(item: Dict) -> Dict:
    # Stored structure uses the same fields we accept, so return cleaned dict
    return {
        "thread_id": item.get("thread_id"),
        "user_message": item.get("user_message"),
        "bot_message": item.get("bot_message"),
        "date": item.get("date"),
        "context": item.get("context", {}),
    }

# -------------------------
# Business logic (DynamoDB-backed)
# -------------------------

def store_chat_log(thread_id: str, chat_log: ChatLog) -> None:
    """
    Store a chat log into DynamoDB. The table must exist and have 'thread_id' as partition key
    and 'date' as a sort key (ISO8601 string). This function avoids filesystem dependencies.
    """
    if chat_table is None:
        raise RuntimeError("DynamoDB table resource not initialized")

    item = {
        "thread_id": thread_id,
        # Use ISO 8601 for range key so sorting works lexicographically
        "date": chat_log.date.isoformat(),
        "user_message": chat_log.user_message.dict(),
        "bot_message": [bm.dict() for bm in chat_log.bot_message],
        "context": chat_log.context or {},
        "created_at": datetime.utcnow().isoformat(),
    }

    chat_table.put_item(Item=item)
    logger.info("chat log stored", extra={"thread_id": thread_id, "date": item["date"]})


def list_threads(limit: int = 10, page: int = 1) -> ChatLogResponse:
    """
    Produce a paginated list of thread summaries. Implementation uses a table scan (ok for small datasets).
    For production, create a GSI or maintain a threads table.
    """
    if chat_table is None:
        raise RuntimeError("DynamoDB table resource not initialized")

    # naive scan
    resp = chat_table.scan(ProjectionExpression="thread_id, #d", ExpressionAttributeNames={"#d": "date"})
    items = resp.get("Items", [])

    # Map latest date per thread
    latest_by_thread: Dict[str, str] = {}
    for it in items:
        tid = it.get("thread_id")
        d = it.get("date")
        if tid is None or d is None:
            continue
        if tid not in latest_by_thread or d > latest_by_thread[tid]:
            latest_by_thread[tid] = d

    # Turn into ChatThreadInfo list
    threads = []
    for tid, d in latest_by_thread.items():
        try:
            threads.append(ChatThreadInfo(thread_id=tid, date=datetime.fromisoformat(d)))
        except Exception:
            # If date parsing fails, skip item
            continue

    # sort by date desc
    threads.sort(key=lambda t: t.date, reverse=True)

    total = len(threads)
    # pagination
    start = (page - 1) * limit
    end = start + limit
    page_threads = threads[start:end]

    return ChatLogResponse(total=total, page=page, limit=limit, conversations=page_threads)


def get_logs_for_thread(thread_id: str) -> List[Dict]:
    if chat_table is None:
        raise RuntimeError("DynamoDB table resource not initialized")

    # Query by partition key (assumes table has thread_id as PK and date as SK)
    try:
        resp = chat_table.query(KeyConditionExpression=boto3.dynamodb.conditions.Key("thread_id").eq(thread_id))
    except Exception as e:
        # Some tables may not have a suitable key; fallback to scan filter
        logger.warning("Query failed, falling back to scan", extra={"error": str(e)})
        resp = chat_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("thread_id").eq(thread_id)
        )

    items = resp.get("Items", [])
    # Sort by date ascending
    items.sort(key=lambda it: it.get("date", ""))

    return [item_to_chatlog(it) for it in items]

# -------------------------
# Lambda handler
# -------------------------

def lambda_handler(event, context):
    """
    API Gateway-compatible Lambda handler. Supports:
      - POST /logs           -> store chat log (requires JSON body with 'thread_id' and ChatLog fields)
      - GET  /threads        -> list threads (query params: limit, page)
      - GET  /logs/{thread}  -> get logs for a specific thread

    Uses environment variables for configuration and writes structured logs to CloudWatch.

    Returns API Gateway proxy response: { statusCode, headers, body }
    """
    start_ts = time.time()
    logger.info("request_start", extra={"event": {k: event.get(k) for k in ["httpMethod", "path", "pathParameters", "queryStringParameters"]}})

    # Timeout pre-check
    rem_ms = remaining_ms(context)
    if rem_ms < TIMEOUT_BUFFER_MS:
        logger.error("Insufficient remaining time, aborting", extra={"remaining_ms": rem_ms})
        return api_response(504, {"error": "Function is near timeout; request aborted"})

    # Normalize request method and path for API Gateway REST proxy
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
    raw_path = event.get("path") or event.get("rawPath")

    try:
        if method == "OPTIONS":
            # CORS preflight
            return api_response(200, {"ok": True})

        # POST /logs
        if method == "POST" and raw_path and raw_path.rstrip("/").endswith("/logs"):
            # Parse body
            body_text = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                # If encoded, decode (API Gateway may base64). Keep simple; caller should not send base64.
                body_text = base64.b64decode(body_text).decode("utf-8")
            try:
                payload = json.loads(body_text)
            except Exception:
                return api_response(400, {"error": "Invalid JSON body"})

            thread_id = payload.get("thread_id")
            if not thread_id:
                return api_response(400, {"error": "Missing required field 'thread_id' in payload"})

            # Validate remaining payload conforms to ChatLog model (excluding thread_id)
            try:
                # Recompose ChatLog-compatible dict
                chatlog_data = {
                    "user_message": payload.get("user_message"),
                    "bot_message": payload.get("bot_message"),
                    "date": payload.get("date"),
                    "context": payload.get("context", {}),
                }
                # Validate/convert
                chat_log = ChatLog(**chatlog_data)
            except ValidationError as ve:
                logger.warning("validation_failed", extra={"errors": ve.errors()})
                return api_response(400, {"error": "validation_failed", "details": ve.errors()})

            # Another timeout check before heavy write
            rem_ms = remaining_ms(context)
            if rem_ms < TIMEOUT_BUFFER_MS:
                logger.error("Insufficient remaining time before DB write", extra={"remaining_ms": rem_ms})
                return api_response(504, {"error": "Function is near timeout; request aborted before write"})

            try:
                store_chat_log(thread_id, chat_log)
            except ClientError as e:
                logger.error("dynamodb_put_failed", extra={"error": str(e)})
                return api_response(500, {"error": "dynamodb_put_failed", "details": str(e)})

            return api_response(201, {"ok": True, "thread_id": thread_id})

        # GET /threads
        if method == "GET" and raw_path and raw_path.rstrip("/").endswith("/threads"):
            qs = event.get("queryStringParameters") or {}
            try:
                limit = int(qs.get("limit", 10))
            except Exception:
                limit = 10
            try:
                page = int(qs.get("page", 1))
            except Exception:
                page = 1

            # Pre-timeout check
            rem_ms = remaining_ms(context)
            if rem_ms < TIMEOUT_BUFFER_MS:
                logger.error("Insufficient remaining time before listing threads", extra={"remaining_ms": rem_ms})
                return api_response(504, {"error": "Function near timeout; aborted listing"})

            try:
                resp_model = list_threads(limit=limit, page=page)
            except Exception as e:
                logger.error("list_threads_failed", extra={"error": str(e)})
                return api_response(500, {"error": "list_threads_failed", "details": str(e)})

            return api_response(200, json.loads(resp_model.json()))

        # GET /logs/{thread_id}
        # Path parameter extraction (API Gateway v1 uses pathParameters)
        path_params = event.get("pathParameters") or {}
        if method == "GET" and (path_params and path_params.get("thread_id")):
            thread_id = path_params.get("thread_id")
            rem_ms = remaining_ms(context)
            if rem_ms < TIMEOUT_BUFFER_MS:
                logger.error("Insufficient remaining time before fetching logs", extra={"remaining_ms": rem_ms})
                return api_response(504, {"error": "Function is near timeout; aborted get logs"})
            try:
                items = get_logs_for_thread(thread_id)
            except Exception as e:
                logger.error("get_logs_failed", extra={"error": str(e)})
                return api_response(500, {"error": "get_logs_failed", "details": str(e)})
            return api_response(200, {"thread_id": thread_id, "logs": items})

        # Unsupported route
        logger.warning("route_not_found", extra={"method": method, "path": raw_path})
        return api_response(404, {"error": "not_found"})

    except Exception as e:
        logger.exception("unhandled_exception", extra={"error": str(e)})
        return api_response(500, {"error": "internal_server_error", "details": str(e)})
    finally:
        elapsed = time.time() - start_ts
        logger.info("request_end", extra={"duration_ms": int(elapsed * 1000)})
