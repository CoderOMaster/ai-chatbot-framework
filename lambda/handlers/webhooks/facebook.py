import os
import json
import hmac
import hashlib
import logging
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)


def _verify_signature(app_secret: str, body: bytes, signature: str) -> bool:
    if not signature:
        return False
    try:
        method, sig = signature.split("=", 1)
    except ValueError:
        return False
    if method.lower() != "sha1":
        return False
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(digest, sig)


async def _forward_http(payload: Dict[str, Any], endpoint: str) -> int:
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(endpoint, json=payload) as resp:
            return resp.status


def handler(event, context):
    # Lambda handler: API Gateway v2 HTTP expected
    app_secret = os.environ.get("FACEBOOK_APP_SECRET", "")
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

    signature = None
    headers = event.get("headers") or {}
    # API GW may lowercase headers
    signature = headers.get("X-Hub-Signature") or headers.get("x-hub-signature")

    if not _verify_signature(app_secret, body_bytes, signature or ""):
        return {"statusCode": 403, "body": json.dumps({"error": "Invalid signature"})}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    # Forward synchronously with basic retry
    import asyncio

    async def do_forward():
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                status = await _forward_http(payload, forwarding_endpoint)
                if status < 500:
                    return status
            except Exception as e:
                logger.exception("Forward error: %s", e)
            await asyncio.sleep(min(2 ** attempts, 5))
        return 502

    status = asyncio.get_event_loop().run_until_complete(do_forward())
    return {"statusCode": status, "body": json.dumps({"ok": status < 400})}