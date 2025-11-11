import os
import json
import logging
from typing import Any, Dict

import aiohttp

logger = logging.getLogger()
logger.setLevel(logging.INFO)


async def _forward_http(endpoint: str, payload: Dict[str, Any]) -> int:
    async with aiohttp.ClientSession() as session:
        async with session.post(endpoint, json=payload) as resp:
            return resp.status


def handler(event, context):
    if event.get("httpMethod") != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "Method not allowed"})}

    body_str = event.get("body") or "{}"
    is_base64 = event.get("isBase64Encoded")
    body_bytes = (body_str.encode("utf-8") if not is_base64 else base64.b64decode(body_str))

    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    # Map to canonical message shape (lightweight)
    user_message = {
        "thread_id": body.get("thread_id"),
        "text": body.get("text"),
        "context": body.get("context", {}),
    }

    forwarding_endpoint = os.environ.get("FORWARDING_ENDPOINT")
    if not forwarding_endpoint:
        return {"statusCode": 500, "body": json.dumps({"error": "Missing FORWARDING_ENDPOINT"})}

    import asyncio
    async def _run():
        status = await _forward_http(forwarding_endpoint, user_message)
        return status

    status = asyncio.run(_run())
    if 200 <= status < 300:
        return {"statusCode": 200, "body": json.dumps({"success": True})}
    return {"statusCode": 502, "body": json.dumps({"error": "Forwarding failed", "status": status})}