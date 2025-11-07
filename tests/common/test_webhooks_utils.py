import json
import types
import sys
import builtins
from typing import Any

import pytest

from ai_chatbot_common import webhooks as webhooks_mod
from ai_chatbot_common.webhooks import (
    verify_facebook_signature,
    forward_http_json,
    send_to_sqs,
    get_env,
)


class DummyResp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text
        self._raised = False

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


def test_verify_facebook_signature_sha1_and_sha256():
    secret = "topsecret"
    body = b"{\"hello\": \"world\"}"

    import hmac, hashlib

    mac1 = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha1).hexdigest()
    mac256 = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()

    assert verify_facebook_signature(secret, body, f"sha1={mac1}") is True
    assert verify_facebook_signature(secret, body, f"sha256={mac256}") is True

    # Wrong signature
    assert verify_facebook_signature(secret, body, f"sha1={'0'*40}") is False
    assert verify_facebook_signature(secret, body, None) is False


def test_verify_facebook_signature_unknown_algo_graceful():
    secret = "topsecret"
    body = b"abc"
    # Uses hashlib by name before '='
    import hashlib, hmac

    mac = hmac.new(secret.encode(), msg=body, digestmod=hashlib.md5).hexdigest()
    assert verify_facebook_signature(secret, body, f"md5={mac}") is True


def test_forward_http_json_success_and_retries(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"json": json, "headers": headers or {}, "timeout": timeout})
        # first call 500, then 200
        if len(calls) == 1:
            return DummyResp(status_code=500, text="err")
        return DummyResp(status_code=201, text="created")

    monkeypatch.setattr(webhooks_mod.requests, "post", fake_post)

    resp = forward_http_json("https://internal/ingest", {"a": 1}, headers={"x": "y"}, retries=2)
    assert resp.status_code == 201
    assert len(calls) == 2
    assert calls[0]["json"] == {"a": 1}
    assert calls[0]["headers"]["x"] == "y"


def test_forward_http_json_raises_on_nonretry_errors(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return DummyResp(status_code=400, text="bad")

    monkeypatch.setattr(webhooks_mod.requests, "post", fake_post)

    with pytest.raises(RuntimeError):
        forward_http_json("https://internal/ingest", {"a": 1})


def test_forward_http_json_network_error(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        raise OSError("boom")

    monkeypatch.setattr(webhooks_mod.requests, "post", fake_post)

    with pytest.raises(OSError):
        forward_http_json("https://internal/ingest", {"a": 1}, retries=1)
    assert calls["n"] == 2


def test_forward_http_json_missing_endpoint():
    with pytest.raises(ValueError):
        forward_http_json("", {"a": 1})


def test_send_to_sqs_requires_boto3(monkeypatch):
    # Ensure boto3 import fails -> RuntimeError
    orig_boto3 = sys.modules.pop("boto3", None)
    orig_botocore = sys.modules.pop("botocore", None)
    try:
        with pytest.raises(RuntimeError):
            send_to_sqs("https://sqs.url/queue", {"x": 1})
    finally:
        if orig_boto3:
            sys.modules["boto3"] = orig_boto3
        if orig_botocore:
            sys.modules["botocore"] = orig_botocore


def test_send_to_sqs_success(monkeypatch):
    # Inject fake boto3
    fake_boto3 = types.SimpleNamespace()

    class FakeSQS:
        def send_message(self, QueueUrl, MessageBody, DelaySeconds=0):  # noqa: N803
            # Ensure JSON body
            body = json.loads(MessageBody)
            assert body == {"x": 1}
            return {"MessageId": "123"}

    fake_boto3.client = lambda name: FakeSQS()
    sys.modules["boto3"] = fake_boto3
    sys.modules["botocore"] = types.ModuleType("botocore")

    try:
        resp = send_to_sqs("https://sqs.url/queue", {"x": 1}, delay_seconds=5)
        assert resp["MessageId"] == "123"
    finally:
        sys.modules.pop("boto3", None)
        sys.modules.pop("botocore", None)


def test_get_env(monkeypatch):
    monkeypatch.delenv("FOO_BAR", raising=False)
    assert get_env("FOO_BAR") is None
    assert get_env("FOO_BAR", "default") == "default"
    monkeypatch.setenv("FOO_BAR", "42")
    assert get_env("FOO_BAR") == "42"