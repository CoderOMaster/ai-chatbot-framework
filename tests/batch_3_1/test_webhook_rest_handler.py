import os
import json
import base64
import asyncio
from types import SimpleNamespace

import builtins
import sys
import types


# Ensure a dummy aiohttp is available before importing the handler module
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

from unittest.mock import AsyncMock, patch

from lambda.handlers.webhooks import rest as rest_handler


def ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def test_rest_success_plain_json(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"

    seen = {}

    async def fake_forward(payload, endpoint):
        seen["payload"] = payload
        seen["endpoint"] = endpoint
        return 200

    monkeypatch.setattr(rest_handler, "_forward_http", fake_forward)
    # avoid real sleep during retries (not used here, but safe)
    monkeypatch.setattr(rest_handler.asyncio, "sleep", AsyncMock(return_value=None))

    event = {
        "body": json.dumps({"thread_id": "t1", "text": "hi", "context": {"a": 1}}),
        "isBase64Encoded": False,
    }

    resp = rest_handler.handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ok"] is True

    assert seen["endpoint"] == os.environ["FORWARDING_ENDPOINT"]
    assert seen["payload"] == {"thread_id": "t1", "text": "hi", "context": {"a": 1}}


def test_rest_base64_default_context_and_retry(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"

    calls = {"count": 0, "last_payload": None}

    async def fake_forward(payload, endpoint):
        calls["count"] += 1
        calls["last_payload"] = payload
        # First two attempts fail with 5xx, third succeeds
        if calls["count"] == 1:
            return 500
        if calls["count"] == 2:
            return 502
        return 201

    monkeypatch.setattr(rest_handler, "_forward_http", fake_forward)
    monkeypatch.setattr(rest_handler.asyncio, "sleep", AsyncMock(return_value=None))

    payload = {"thread_id": "t2", "text": "hello"}
    b = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    event = {"body": b, "isBase64Encoded": True}

    resp = rest_handler.handler(event, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"]) 
    assert body["ok"] is True
    assert calls["count"] == 3
    # context should default to {}
    assert calls["last_payload"] == {"thread_id": "t2", "text": "hello", "context": {}}


def test_rest_invalid_json_returns_400(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"

    # Make sure it's not reached
    monkeypatch.setattr(rest_handler, "_forward_http", AsyncMock(return_value=200))

    event = {"body": "{not json}", "isBase64Encoded": False}
    resp = rest_handler.handler(event, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"]) 
    assert body["error"] == "Invalid JSON"


def test_rest_missing_forwarding_endpoint_returns_500(monkeypatch):
    ensure_event_loop()
    if "FORWARDING_ENDPOINT" in os.environ:
        del os.environ["FORWARDING_ENDPOINT"]

    event = {"body": json.dumps({}), "isBase64Encoded": False}
    resp = rest_handler.handler(event, None)
    assert resp["statusCode"] == 500
    assert json.loads(resp["body"]).get("error") == "FORWARDING_ENDPOINT not set"


def test_rest_forward_raises_returns_502(monkeypatch):
    ensure_event_loop()
    os.environ["FORWARDING_ENDPOINT"] = "https://example.com/hook"

    async def boom(payload, endpoint):
        raise RuntimeError("network down")

    monkeypatch.setattr(rest_handler, "_forward_http", boom)
    monkeypatch.setattr(rest_handler.asyncio, "sleep", AsyncMock(return_value=None))

    event = {"body": json.dumps({"thread_id": "t3", "text": "yo"}), "isBase64Encoded": False}
    resp = rest_handler.handler(event, None)
    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]).get("ok") is False