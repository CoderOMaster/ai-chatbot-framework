import os
import json
import hmac
import hashlib
import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    try:
        algo, sig = signature.split("=", 1)
    except ValueError:
        return False
    if algo.lower() != "sha1":
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(digest, sig)


async def _forward_http(endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> int:
    async with aiohttp.ClientSession() as session:
        async with session.post(endpoint, json=payload, headers=headers) as resp:
            return resp.status


def handler(event, context):
    # Minimal sync wrapper for AWS Lambda
    # event comes from API Gateway (proxy)
    http_method = event.get("httpMethod")
    if http_method == "GET":
        # Verification
        params = event.get("queryStringParameters") or {}
        hub_mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        app_secret = os.environ.get("FACEBOOK_APP_SECRET", "")
        # If no app secret configured, reject
        if not app_secret:
            return {"statusCode": 500, "body": json.dumps({"error": "Missing FACEBOOK_APP_SECRET"})}
        if hub_mode == "subscribe" and token:
            # We cannot verify token here without stored value; assume it equals app secret or configured VERIFY_TOKEN
            verify_token = os.environ.get("FACEBOOK_VERIFY_TOKEN", app_secret)
            if token == verify_token:
                return {"statusCode": 200, "body": str(challenge)}
            return {"statusCode": 403, "body": json.dumps({"error": "Invalid verification token"})}
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid request parameters"})}

    if http_method != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "Method not allowed"})}

    app_secret = os.environ.get("FACEBOOK_APP_SECRET", "")
    body_str = event.get("body") or "{}"
    is_base64 = event.get("isBase64Encoded")
    body_bytes = (body_str.encode("utf-8") if not is_base64 else base64.b64decode(body_str))

    signature = None
    headers = event.get("headers") or {}
    # Headers could be lower/upper cased
    for k, v in headers.items():
        if k.lower() == "x-hub-signature":
            signature = v
            break

    if not _verify_signature(body_bytes, signature or "", app_secret):
        return {"statusCode": 403, "body": json.dumps({"error": "Invalid request signature"})}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    forwarding_endpoint = os.environ.get("FORWARDING_ENDPOINT")
    if not forwarding_endpoint:
        return {"statusCode": 500, "body": json.dumps({"error": "Missing FORWARDING_ENDPOINT"})}

    # Run the async forwarder using asyncio.run to keep handler sync as required by Lambda default
    import asyncio
    async def _run():
        status = await _forward_http(forwarding_endpoint, payload)
        return status

    status = asyncio.run(_run())
    if 200 <= status < 300:
        return {"statusCode": 200, "body": json.dumps({"success": True})}
    return {"statusCode": 502, "body": json.dumps({"error": "Forwarding failed", "status": status})}