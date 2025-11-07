import json
import os
import base64

from lambda_handlers.llm.zero_shot import handler
from lambda_handlers.llm import zero_shot as zs


def test_invalid_json_body_returns_400():
    event = {"body": "not-json"}
    resp = handler(event, None)
    assert resp["statusCode"] == 400
    assert "Invalid JSON body" in json.loads(resp["body"])['error']


def test_base64_body_and_normalization(monkeypatch):
    # Force classify to avoid network
    monkeypatch.setattr(zs, "_classify_zero_shot", lambda *a, **k: {"intent": 123, "entities": ["x"]})
    body = {"text": "hello"}
    b64 = base64.b64encode(json.dumps(body).encode()).decode()
    event = {"body": b64, "isBase64Encoded": True}
    resp = handler(event, None)
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    # Intent coerced to string, entities non-dict -> {}
    assert data == {"intent": "123", "entities": {}}


def test_direct_invoke_minimal_lists(monkeypatch):
    monkeypatch.setattr(zs, "_classify_zero_shot", lambda *a, **k: {"intent": "foo", "entities": {"a": None}})
    event = {"text": "hi"}
    resp = handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"intent": "foo", "entities": {"a": None}}


def test_handler_returns_500_on_internal_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad stuff")
    monkeypatch.setattr(zs, "_classify_zero_shot", boom)
    event = {"text": "hi"}
    resp = handler(event, None)
    assert resp["statusCode"] == 500
    assert "Failed to classify" in json.loads(resp["body"])['error']