import json
import base64
import pytest
from unittest import mock
from app.lambda.handlers.webhooks import rest as rest_handler


def test_handler_invalid_event_returns_400():
    res = rest_handler.handler("not-a-dict", None)
    assert res["statusCode"] == 400


def test_handler_invalid_json_returns_400():
    event = {"body": "not-json", "isBase64Encoded": False}
    res = rest_handler.handler(event, None)
    assert res["statusCode"] == 400


def test_handler_canonical_mapping_and_no_forwarding_returns_500(monkeypatch):
    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)
    monkeypatch.delenv("FORWARDING_ENDPOINT", raising=False)
    payload = {"thread_id": "t1", "text": "hi", "context": {}}
    body = json.dumps(payload).encode("utf-8")
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False}
    res = rest_handler.handler(event, None)
    assert res["statusCode"] == 500


def test_handler_forward_to_sqs_success(monkeypatch):
    monkeypatch.setenv("FORWARDING_SQS_URL", "https://sqs.local/queue")
    payload = {"thread_id": "t1", "text": "hi"}
    body = json.dumps(payload).encode("utf-8")
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False}

    monkeypatch.setattr(rest_handler, "_push_to_sqs", lambda url, message: {"MessageId": "abc"})
    res = rest_handler.handler(event, None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == {"success": True}


def test_handler_forward_to_endpoint_failure(monkeypatch):
    monkeypatch.setenv("FORWARDING_ENDPOINT", "https://example.invalid")
    payload = {"thread_id": "t1", "text": "hi"}
    body = json.dumps(payload).encode("utf-8")
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False}

    monkeypatch.setattr(rest_handler, "_post_with_retries", lambda url, p: (_ for _ in ()).throw(Exception("fail")))
    res = rest_handler.handler(event, None)
    assert res["statusCode"] == 502


def test_handler_no_forwarding_config_returns_500(monkeypatch):
    monkeypatch.delenv("FORWARDING_SQS_URL", raising=False)
    monkeypatch.delenv("FORWARDING_ENDPOINT", raising=False)
    payload = {"foo": "bar"}
    body = json.dumps(payload).encode("utf-8")
    event = {"body": body.decode("utf-8"), "isBase64Encoded": False}
    res = rest_handler.handler(event, None)
    assert res["statusCode"] == 500