import os
import json
import logging
import time
import traceback
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ---------------------------------------------------------------------------
# Initialization (runs on cold start)
# ---------------------------------------------------------------------------

# Read configuration from environment variables
REGION = os.getenv("REGION", "us-east-1")
BUCKET_NAME = os.getenv("BUCKET_NAME")
TABLE_NAME = os.getenv("TABLE_NAME")
DEFAULT_KEY = os.getenv("DEFAULT_KEY", "default-key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
OPERATION_MODE = os.getenv("OPERATION_MODE", "read")  # example: read or write
TIMEOUT_SAFETY_MS = int(os.getenv("TIMEOUT_SAFETY_MS", "500"))  # ms to keep as buffer

# Initialize structured JSON logger
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach any extras if provided
        if hasattr(record, "extra"):
            payload["extra"] = record.extra
        # Attach exception info if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(LOG_LEVEL)

# Initialize AWS resources outside handler (cold start optimization)
session = boto3.Session(region_name=REGION)
s3_client = session.client("s3")
dynamodb_resource = session.resource("dynamodb") if TABLE_NAME else None
table = dynamodb_resource.Table(TABLE_NAME) if dynamodb_resource and TABLE_NAME else None

logger.info(
    "cold_start_init",
    extra={
        "extra": {
            "region": REGION,
            "bucket": BUCKET_NAME,
            "table": TABLE_NAME,
            "operation_mode": OPERATION_MODE,
        }
    },
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_response(status_code: int, body: Any, headers: Optional[Dict[str, str]] = None) -> Dict:
    """Return API Gateway v1/v2 compatible response."""
    base_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": os.getenv("CORS_ORIGIN", "*"),
    }
    if headers:
        base_headers.update(headers)
    return {"statusCode": status_code, "headers": base_headers, "body": json.dumps(body)}


def _remaining_ms(context) -> int:
    try:
        return int(context.get_remaining_time_in_millis())
    except Exception:
        # If context not provided or missing, assume plenty of time
        return 60_000


class TimeoutError(RuntimeError):
    pass


def _ensure_time(context, required_ms: int = 0):
    """Raise TimeoutError if remaining time is too small for required_ms plus safety.
    required_ms is estimated time needed to complete the next operation.
    """
    remaining = _remaining_ms(context)
    if remaining < (required_ms + TIMEOUT_SAFETY_MS):
        raise TimeoutError(f"Not enough remaining time: {remaining}ms, need {required_ms + TIMEOUT_SAFETY_MS}ms")


def fetch_from_dynamodb(key: str, context=None) -> Optional[Dict[str, Any]]:
    if not table:
        logger.warning("dynamodb_not_configured", extra={"extra": {"table": TABLE_NAME}})
        return None
    _ensure_time(context)
    try:
        logger.info("dynamodb_get_item", extra={"extra": {"key": key}})
        resp = table.get_item(Key={"id": key})
        return resp.get("Item")
    except (BotoCoreError, ClientError) as e:
        logger.error("dynamodb_error", extra={"extra": {"error": str(e), "trace": traceback.format_exc()}})
        return None


def fetch_from_s3(key: str, context=None) -> Optional[bytes]:
    if not BUCKET_NAME:
        logger.warning("s3_not_configured", extra={"extra": {"bucket": BUCKET_NAME}})
        return None
    _ensure_time(context)
    try:
        logger.info("s3_get_object", extra={"extra": {"bucket": BUCKET_NAME, "key": key}})
        resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        return resp["Body"].read()
    except ClientError as e:
        logger.warning("s3_object_missing_or_error", extra={"extra": {"error": str(e)}})
        return None
    except BotoCoreError as e:
        logger.error("s3_error", extra={"extra": {"error": str(e), "trace": traceback.format_exc()}})
        return None


def put_to_dynamodb(item: Dict[str, Any], context=None) -> bool:
    if not table:
        logger.warning("dynamodb_not_configured", extra={"extra": {"table": TABLE_NAME}})
        return False
    _ensure_time(context)
    try:
        logger.info("dynamodb_put_item", extra={"extra": {"item": item}})
        table.put_item(Item=item)
        return True
    except (BotoCoreError, ClientError) as e:
        logger.error("dynamodb_put_error", extra={"extra": {"error": str(e), "trace": traceback.format_exc()}})
        return False


def put_to_s3(key: str, data: bytes, context=None) -> bool:
    if not BUCKET_NAME:
        logger.warning("s3_not_configured", extra={"extra": {"bucket": BUCKET_NAME}})
        return False
    _ensure_time(context)
    try:
        logger.info("s3_put_object", extra={"extra": {"bucket": BUCKET_NAME, "key": key}})
        s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=data)
        return True
    except (BotoCoreError, ClientError) as e:
        logger.error("s3_put_error", extra={"extra": {"error": str(e), "trace": traceback.format_exc()}})
        return False


# ---------------------------------------------------------------------------
# Lambda Handler
# ---------------------------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda handler intended to be fronted by API Gateway (HTTP API or REST API).

    Supported flows:
      - GET: fetch item by query string parameter 'key' from DynamoDB (id) or S3 object
      - POST: store JSON body to DynamoDB (requires id in body) and optional s3_key

    Returns API Gateway compatible response.
    """
    request_id = getattr(context, "aws_request_id", None)
    start_ts = time.time()
    logger.info("request_received", extra={"extra": {"request_id": request_id, "event": event}})

    try:
        # Guard for imminent timeouts
        _ensure_time(context)

        http_method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
        # Normalize GET vs other
        if http_method and http_method.upper() == "GET":
            qs = event.get("queryStringParameters") or {}
            key = qs.get("key") if qs else None
            key = key or DEFAULT_KEY

            # First try DynamoDB
            item = fetch_from_dynamodb(key, context=context)
            if item:
                elapsed = time.time() - start_ts
                logger.info("respond_ok_dynamodb", extra={"extra": {"key": key, "elapsed_s": elapsed}})
                return _api_response(200, {"source": "dynamodb", "item": item})

            # Fallback to S3
            obj = fetch_from_s3(key, context=context)
            if obj is not None:
                # Return base64 encoded content to be safe if binary
                try:
                    text = obj.decode("utf-8")
                    body = {"source": "s3", "content": text}
                except Exception:
                    import base64

                    body = {"source": "s3", "content_base64": base64.b64encode(obj).decode("utf-8")}

                elapsed = time.time() - start_ts
                logger.info("respond_ok_s3", extra={"extra": {"key": key, "elapsed_s": elapsed}})
                return _api_response(200, body)

            # Not found
            logger.info("not_found", extra={"extra": {"key": key}})
            return _api_response(404, {"message": "Item not found", "key": key})

        # POST: create/update
        if http_method and http_method.upper() == "POST":
            body_text = event.get("body")
            if event.get("isBase64Encoded"):
                import base64

                body_text = base64.b64decode(body_text).decode("utf-8")
            try:
                body = json.loads(body_text) if body_text else {}
            except Exception:
                logger.warning("post_body_not_json", extra={"extra": {"raw": body_text}})
                return _api_response(400, {"message": "Request body must be valid JSON"})

            # Expect 'id' in body to store in DynamoDB
            item_id = body.get("id")
            if not item_id:
                return _api_response(400, {"message": "Missing 'id' in body"})

            # Optional: store an 's3_key' with raw payload
            s3_key = body.get("s3_key")
            if s3_key:
                # store serialized JSON in s3
                data = json.dumps(body).encode("utf-8")
                ok = put_to_s3(s3_key, data, context=context)
                if not ok:
                    return _api_response(500, {"message": "Failed to write to S3"})

            # store selected attributes to DynamoDB (put whole body for simplicity)
            ok = put_to_dynamodb(body, context=context)
            if not ok:
                return _api_response(500, {"message": "Failed to write to DynamoDB"})

            return _api_response(201, {"message": "Stored", "id": item_id})

        # If not an HTTP API event, attempt a generic handler: read 'key' from event
        key = event.get("key") or DEFAULT_KEY
        item = fetch_from_dynamodb(key, context=context)
        if item:
            return {"statusCode": 200, "body": json.dumps({"source": "dynamodb", "item": item})}

        obj = fetch_from_s3(key, context=context)
        if obj:
            try:
                text = obj.decode("utf-8")
                content = text
            except Exception:
                import base64

                content = base64.b64encode(obj).decode("utf-8")
            return {"statusCode": 200, "body": json.dumps({"source": "s3", "content": content})}

        return {"statusCode": 404, "body": json.dumps({"message": "Not Found"})}

    except TimeoutError as e:
        logger.error("timeout_imminent", extra={"extra": {"error": str(e)}})
        return _api_response(504, {"message": "Function timeout imminent, request aborted"})
    except Exception as e:
        logger.error("handler_exception", extra={"extra": {"error": str(e), "trace": traceback.format_exc()}})
        return _api_response(500, {"message": "Internal server error"})

