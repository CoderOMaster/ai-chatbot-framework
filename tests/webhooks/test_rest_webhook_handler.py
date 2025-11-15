import json
import base64
import importlib.util
from pathlib import Path

import pytest


def load_rest_module():
    path = Path(__file__).resolve().parents[2] / "lambda" / "handlers" / "webhooks" / "rest.py"
    spec = importlib.util.spec_from_file_location("lambda_handlers.webhooks.rest", str(path))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


rest = load_rest_module()


def test_non_post_returns_405():
    event = {"httpMethod": "GET"}
    res = rest.handler(event, context=None)
    assert res["statusCode"] == 405
    assert "Method not allowed" in res["body"]


def test_invalid_json_returns_400():
    event = {"httpMethod": "POST", "body": "{"}
    res = rest.handler(event, context=None)
    assert res["statusCode"] == 400
    assert "Invalid JSON" in res["body"]


def test_missing_forwarding_endpoint_returns_500(monkeypatch):
    event = {"httpMethod": "POST", "body": json.dumps({"thread_id": "t1", "text": "hi"})}
    # Ensure env not set
    monkeypatch.delenv("FORWARDING_ENDPOINT", raising=False)
    res = rest.handler(event, context=None)
    assert res["statusCode"] == 500
    assert "Missing FORWARDING_ENDPOINT" in res["body"]


def test_forward_success_returns_200(monkeypatch):
    calls = {}

    async def fake_forward(url, payload):
        calls["url"] = url
        calls["payload"] = payload
        return 202

    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/api")
    monkeypatch.setattr(rest, "_forward_http", fake_forward, raising=True)

    event = {"httpMethod": "POST", "body": json.dumps({"thread_id": "t2", "text": "hello", "context": {"a": 1}})}
    res = rest.handler(event, context=None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]).get("success") is True

    assert calls["url"] == "https://internal/api"
    assert calls["payload"] == {"thread_id": "t2", "text": "hello", "context": {"a": 1}}


def test_forward_failure_returns_502(monkeypatch):
    async def fake_forward(url, payload):
        return 500

    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/api")
    monkeypatch.setattr(rest, "_forward_http", fake_forward, raising=True)

    event = {"httpMethod": "POST", "body": json.dumps({"thread_id": "t3", "text": "oops"})}
    res = rest.handler(event, context=None)
    assert res["statusCode"] == 502
    body = json.loads(res["body"])
    assert body["error"] == "Forwarding failed"
    assert body["status"] == 500


def test_base64_body_decoded_and_forwarded(monkeypatch):
    # Verify that when event is base64 encoded, handler decodes and forwards correctly
    payload = {"thread_id": "T99", "text": "hey", "context": {"x": 2}}
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

    seen = {}

    async def fake_forward(url, user_message):
        seen["url"] = url
        seen["user_message"] = user_message
        return 200

    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://svc/endpoint")
    monkeypatch.setattr(rest, "_forward_http", fake_forward, raising=True)

    event = {"httpMethod": "POST", "body": encoded, "isBase64Encoded": True}
    res = rest.handler(event, context=None)
    assert res["statusCode"] == 200
    assert seen["url"] == "https://svc/endpoint"
    # Ensure mapping preserves keys and defaults context
    assert seen["user_message"] == {"thread_id": "T99", "text": "hey", "context": {"x": 2}}