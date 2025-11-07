import json
import logging
import os
from typing import Any, Dict, Optional

from ai_chatbot_common.webhooks import (
    verify_facebook_signature,
    forward_http_json,
    send_to_sqs,
    get_env,
)

logger = logging.getLogger(__name__)


def _lower_headers(headers: Optional[Dict[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not headers:
        return result
    for k, v in headers.items():
        if isinstance(v, list):
            # take first
            result[k.lower()] = v[0]
        else:
            result[k.lower()] = str(v)
    return result


def _get_body(event: Dict[str, Any]) -> bytes:
    body = event.get("body", "")
    if isinstance(body, (dict, list)):
        return json.dumps(body).encode("utf-8")
    if event.get("isBase64Encoded"):
        import base64

        return base64.b64decode(body)
    return (body or "").encode("utf-8")


def _ok(body: Any) -> Dict[str, Any]:
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _error(status: int, message: str) -> Dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}


def _handle_get_verify(event: Dict[str, Any]) -> Dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    hub_mode = qs.get("hub.mode")
    token = qs.get("hub.verify_token")
    challenge = qs.get("hub.challenge")

    verify_token = get_env("FACEBOOK_VERIFY_TOKEN")

    if hub_mode and token and challenge and verify_token:
        if hub_mode == "subscribe" and token == verify_token:
            return {"statusCode": 200, "headers": {"Content-Type": "text/plain"}, "body": str(challenge)}
        return _error(403, "Invalid verification token")

    return _error(400, "Invalid request parameters")


def _forward_messages(entries: Any) -> None:
    forwarding_sqs = get_env("FORWARDING_SQS_URL")
    forwarding_endpoint = get_env("FORWARDING_ENDPOINT")

    for entry in entries or []:
        page_id = entry.get("id")
        for messaging_event in entry.get("messaging", []):
            sender_id = (messaging_event.get("sender") or {}).get("id")
            if not sender_id:
                continue
            timestamp = messaging_event.get("timestamp")
            is_postback = bool(messaging_event.get("postback"))
            text: Optional[str] = None
            if messaging_event.get("message") and "text" in messaging_event["message"]:
                text = messaging_event["message"]["text"]
            elif is_postback:
                text = (messaging_event.get("postback") or {}).get("payload")

            if text is None:
                continue

            user_message = {
                "thread_id": sender_id,
                "text": text,
                "context": {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": timestamp,
                    "is_postback": is_postback,
                },
            }

            if forwarding_sqs:
                send_to_sqs(forwarding_sqs, user_message)
            else:
                headers = {"x-source": "facebook-webhook"}
                forward_http_json(forwarding_endpoint or "", user_message, headers=headers)



def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "POST").upper()

    if method == "GET":
        return _handle_get_verify(event)

    headers = _lower_headers(event.get("headers"))
    signature = headers.get("x-hub-signature") or headers.get("x-hub-signature-256")

    app_secret = os.getenv("FACEBOOK_APP_SECRET", "")
    raw_body = _get_body(event)

    if not app_secret or not verify_facebook_signature(app_secret, raw_body, signature):
        return _error(403, "Invalid request signature")

    try:
        data = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    try:
        _forward_messages(data.get("entry"))
        return _ok({"success": True})
    except Exception as e:
        logger.exception("Error processing webhook")
        return _error(500, f"Error processing webhook: {e}")