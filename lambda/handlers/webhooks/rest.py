import os
import json
import logging
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)


async def _forward_http(payload: Dict[str, Any], endpoint: str) -> int:
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(endpoint, json=payload) as resp:
            return resp.status


def handler(event, context):
    forwarding_endpoint = os.environ.get("FORWARDING_ENDPOINT")
    if not forwarding_endpoint:
        return {"statusCode": 500, "body": json.dumps({"error": "FORWARDING_ENDPOINT not set"})}

    body = event.get("body", "") or ""
    is_base64 = event.get("isBase64Encoded", False)
    if is_base64:
        import base64
        body_bytes = base64.b64decode(body)
    else:
        body_bytes = body.encode("utf-8")

    try:
        incoming = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    # Map to canonical UserMessage shape
    user_message = {
        "thread_id": incoming.get("thread_id"),
        "text": incoming.get("text"),
        "context": incoming.get("context", {}),
    }

    import asyncio

    async def do_forward():
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                status = await _forward_http(user_message, forwarding_endpoint)
                if status < 500:
                    return status
            except Exception as e:
                logger.exception("Forward error: %s", e)
            await asyncio.sleep(min(2 ** attempts, 5))
        return 502

    status = asyncio.get_event_loop().run_until_complete(do_forward())
    return {"statusCode": status, "body": json.dumps({"ok": status < 400})}