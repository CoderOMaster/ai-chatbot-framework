import os
import json
import base64
import hmac
import hashlib
from unittest import mock
import pytest
from lambda.handlers.webhooks import facebook

fb_handler = facebook.handler


def make_sig(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha1)
    return f"sha1={mac.hexdigest()}"


def test_handler_invalid_event_returns_400(monkeypatch):
    res = fb_handler.handler("not-a-dict", None)
    assert res["statusCode"] == 400


def test_handler_invalid_json_returns_400(monkeypatch):
    event = {"body": "not-json", "isBase64Encoded": False}
    res = fb_handler.handler(event, None)
    assert res["statusCode"] == 400


def test_handler_missing_secret_skips_verification(monkeypatch):
    # ensure env var not set
    monkeypatch.delenv("FACEBOOK_APP_SECRET", raising=False)
    payload = {"a": 1}
    body = json.dumps(payload).encode("utf-8")
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False, "headers": {}}
    res = fb_handler.handler(event, None)
    assert res["statusCode"] == 500


def test_handler_invalid_signature_returns_403(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "s")
    payload = {"a": 1}
    body = json.dumps(payload).encode("utf-8")
    sig = make_sig("othersecret", body)
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False, "headers": {"X-Hub-Signature": sig}}
    res = fb_handler.handler(event, None)
    assert res["statusCode"] == 403


def test_handler_forward_to_sqs_success(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "s")
    monkeypatch.setenv("FORWARDING_SQS_URL", "https://sqs.local/queue")
    payload = {"a": 1}
    body = json.dumps(payload).encode("utf-8")
    sig = make_sig("s", body)
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False, "headers": {"X-Hub-Signature": sig}}

    class FakeClient:
        def send_message(self, QueueUrl, MessageBody):
            return {"MessageId": "123"}

    monkeypatch.setattr(fb_handler, "_sqs_client", FakeClient())
    res = fb_handler.handler(event, None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == {"success": True}


def test_handler_forward_to_endpoint_failure(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "s")
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://example.invalid")
    payload = {"a": 1}
    body = json.dumps(payload).encode("utf-8")
    sig = make_sig("s", body)
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False, "headers": {"X-Hub-Signature": sig}}

    # make _post_with_retries raise
    monkeypatch.setattr(fb_handler, "_post_with_retries", lambda url, p: (_ for _ in ()).throw(Exception("fail")))
    res = fb_handler.handler(event, None)
    assert res["statusCode"] == 502


def test_handler_no_forwarding_config_returns_500(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "s")
    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)
    monkeypatch.delenv("FORWARDING_ENDPOINT", raising=False)
    payload = {"a": 1}
    body = json.dumps(payload).encode("utf-8")
    sig = make_sig("s", body)
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False, "headers": {"X-Hub-Signature": sig}}
    res = fb_handler.handler(event, None)
    assert res["statusCode"] == 500