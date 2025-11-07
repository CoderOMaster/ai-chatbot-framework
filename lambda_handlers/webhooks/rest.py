import json
import logging
import os
from typing import Any, Dict

from ai_chatbot_common.webhooks import forward_http_json, send_to_sqs, get_env

logger = logging.getLogger(__name__)


def _get_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body", "")
    if isinstance(body, dict):
        return body
    if event.get("isBase64Encoded"):
        import base64

        decoded = base64.b64decode(body or "").decode("utf-8")
        return json.loads(decoded or "{}")
    return json.loads((body or "").decode("utf-8") if isinstance(body, (bytes, bytearray)) else (body or "{}"))


def _ok(body: Any) -> Dict[str, Any]:
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _error(status: int, message: str) -> Dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}


def _to_user_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Accept already canonical payload or map common shapes
    if all(k in payload for k in ("thread_id", "text", "context")):
        return payload

    thread_id = payload.get("thread_id") or payload.get("sender_id") or payload.get("user") or "anonymous"
    text = payload.get("text") or payload.get("message") or ""
    context = payload.get("context") or {k: v for k, v in payload.items() if k not in ("thread_id", "text", "message")}

    return {"thread_id": thread_id, "text": text, "context": context}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if (event.get("httpMethod") or "POST").upper() != "POST":
        return _error(405, "Method Not Allowed")

    try:
        payload = _get_body(event)
    except Exception:
        return _error(400, "Invalid JSON body")

    message = _to_user_message(payload)

    try:
        forwarding_sqs = get_env("FORWARDING_SQS_URL")
        forwarding_endpoint = get_env("FORWARDING_ENDPOINT")
        if forwarding_sqs:
            send_to_sqs(forwarding_sqs, message)
        else:
            headers = {"x-source": "rest-webhook"}
            forward_http_json(forwarding_endpoint or "", message, headers=headers)
        return _ok({"success": True})
    except Exception as e:
        logger.exception("Failed to forward webhook message")
        return _error(500, f"Failed to forward message: {e}")