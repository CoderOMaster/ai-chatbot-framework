import json
import os
import hmac
import hashlib
import base64
import importlib.util
from pathlib import Path

import pytest


def load_fb_module():
    path = Path(__file__).resolve().parents[2] / "lambda" / "handlers" / "webhooks" / "facebook.py"
    spec = importlib.util.spec_from_file_location("lambda_handlers.webhooks.facebook", str(path))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


fb = load_fb_module()


def sign(secret: str, body: bytes) -> str:
    return "sha1=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha1).hexdigest()


def test_get_missing_app_secret_returns_500(monkeypatch):
    monkeypatch.delenv("FACEBOOK_APP_SECRET", raising=False)
    event = {"httpMethod": "GET", "queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "123"}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 500
    assert "Missing FACEBOOK_APP_SECRET" in res["body"]


def test_get_verify_success_with_token_env(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "token123")
    event = {"httpMethod": "GET", "queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "token123", "hub.challenge": "777"}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 200
    assert res["body"] == "777"


def test_get_verify_invalid_token_returns_403(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FACEBOOK_VERIFY_TOKEN", "right")
    event = {"httpMethod": "GET", "queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "abc"}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 403


def test_get_invalid_params_returns_400(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    event = {"httpMethod": "GET", "queryStringParameters": {"foo": "bar"}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 400


def test_non_post_returns_405():
    event = {"httpMethod": "PUT"}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 405


def test_post_invalid_signature_returns_403(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    body = json.dumps({"a": 1}).encode("utf-8")
    event = {"httpMethod": "POST", "body": body.decode("utf-8"), "headers": {"X-Hub-Signature": "sha1=deadbeef"}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 403


def test_post_valid_signature_forward_success(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/forward")

    body_bytes = json.dumps({"entry": [1]}).encode("utf-8")
    hdr_sig = sign("secret", body_bytes)

    async def fake_forward(url, payload, headers=None):
        assert url == "https://internal/forward"
        assert payload == {"entry": [1]}
        return 204

    monkeypatch.setattr(fb, "_forward_http", fake_forward, raising=True)

    event = {"httpMethod": "POST", "body": body_bytes.decode("utf-8"), "headers": {"X-Hub-Signature": hdr_sig}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]).get("success") is True


def test_post_valid_signature_forward_failure(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://internal/forward")

    body_bytes = json.dumps({"x": 2}).encode("utf-8")
    hdr_sig = sign("secret", body_bytes)

    async def fake_forward(url, payload, headers=None):
        return 503

    monkeypatch.setattr(fb, "_forward_http", fake_forward, raising=True)

    event = {"httpMethod": "POST", "body": body_bytes.decode("utf-8"), "headers": {"X-Hub-Signature": hdr_sig}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 502


def test_post_invalid_json_returns_400(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    body_bytes = b"{"  # invalid JSON
    hdr_sig = sign("secret", body_bytes)
    event = {"httpMethod": "POST", "body": body_bytes.decode("utf-8"), "headers": {"X-Hub-Signature": hdr_sig}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 400


def test_post_missing_forwarding_endpoint_returns_500(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.delenv("FORWARDING_ENDPOINT", raising=False)
    body_bytes = json.dumps({"a": 1}).encode("utf-8")
    hdr_sig = sign("secret", body_bytes)
    event = {"httpMethod": "POST", "body": body_bytes.decode("utf-8"), "headers": {"X-Hub-Signature": hdr_sig}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 500
    assert "Missing FORWARDING_ENDPOINT" in res["body"]


def test_post_base64_body_supported(monkeypatch):
    # When API Gateway sends base64-encoded body, handler should decode and verify signature against decoded bytes
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secret")
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://forward")

    payload = {"msg": "hi"}
    body_bytes = json.dumps(payload).encode("utf-8")
    hdr_sig = sign("secret", body_bytes)
    encoded = base64.b64encode(body_bytes).decode("ascii")

    async def fake_forward(url, pld, headers=None):
        assert pld == payload
        return 200

    monkeypatch.setattr(fb, "_forward_http", fake_forward, raising=True)

    event = {"httpMethod": "POST", "body": encoded, "isBase64Encoded": True, "headers": {"X-Hub-Signature": hdr_sig}}
    res = fb.handler(event, context=None)
    assert res["statusCode"] == 200


def test_verify_signature_edge_cases():
    body = b"{}"
    # Missing signature
    assert fb._verify_signature(body, "", "secret") is False
    # Malformed header
    assert fb._verify_signature(body, "notvalid", "secret") is False
    # Wrong algo
    sig = "sha256=" + hashlib.sha256(b"x").hexdigest()
    assert fb._verify_signature(body, sig, "secret") is False