import os
import json
import hmac
import hashlib
import base64
import asyncio
import sys
import types

from unittest.mock import AsyncMock

# Provide a dummy aiohttp so import doesn't fail
class _DummyAiohttp(types.SimpleNamespace):
    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class ClientSession:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def post(self, *args, **kwargs):
            raise RuntimeError("Dummy aiohttp should not be used in tests; _forward_http must be patched")


if "aiohttp" not in sys.modules:
    sys.modules["aiohttp"] = _DummyAiohttp()

from lambda.handlers.webhooks import facebook as fb_handler


def ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def sign(app_secret: str, body: bytes) -> str:
    sig = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha1).hexdigest()
    return f"sha1={sig}"


def test_facebook_happy_path_with_retries(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"
    os.environ["FACEBOOK_APP_SECRET"] = "secret"

    attempts = {"n": 0}

    async def fake_forward(payload, endpoint):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return 503
        return 202

    monkeypatch.setattr(fb_handler, "_forward_http", fake_forward)
    monkeypatch.setattr(fb_handler.asyncio, "sleep", AsyncMock(return_value=None))

    payload = {"object": "page", "entry": []}
    body_bytes = json.dumps(payload).encode("utf-8")
    event = {
        "body": body_bytes.decode("utf-8"),
        "isBase64Encoded": False,
        "headers": {"X-Hub-Signature": sign(os.environ["FACEBOOK_APP_SECRET"], body_bytes)},
    }

    resp = fb_handler.handler(event, None)
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"]) == {"ok": True}
    assert attempts["n"] == 3


def test_facebook_invalid_signature(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"
    os.environ["FACEBOOK_APP_SECRET"] = "secret"

    body_bytes = b"{}"
    event = {
        "body": body_bytes.decode("utf-8"),
        "isBase64Encoded": False,
        "headers": {"X-Hub-Signature": "sha1=deadbeef"},
    }

    resp = fb_handler.handler(event, None)
    assert resp["statusCode"] == 403
    assert json.loads(resp["body"]).get("error") == "Invalid signature"


def test_facebook_invalid_json_returns_400(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"
    os.environ["FACEBOOK_APP_SECRET"] = "secret"

    bad_body = "{not json}"
    sig = sign(os.environ["FACEBOOK_APP_SECRET"], bad_body.encode("utf-8"))

    resp = fb_handler.handler({"body": bad_body, "isBase64Encoded": False, "headers": {"x-hub-signature": sig}}, None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]).get("error") == "Invalid JSON"


def test_facebook_missing_forwarding_endpoint_returns_500(monkeypatch):
    ensure_event_loop()
    if "FORWARDING_ENDPOINT" in os.environ:
        del os.environ["FORWARDING_ENDPOINT"]
    os.environ["FACEBOOK_APP_SECRET"] = "secret"

    payload = {}
    body_bytes = json.dumps(payload).encode("utf-8")
    event = {
        "body": base64.b64encode(body_bytes).decode("ascii"),
        "isBase64Encoded": True,
        "headers": {"x-hub-signature": sign(os.environ["FACEBOOK_APP_SECRET"], body_bytes)},
    }

    resp = fb_handler.handler(event, None)
    assert resp["statusCode"] == 500
    assert json.loads(resp["body"]).get("error") == "FORWARDING_ENDPOINT not set"