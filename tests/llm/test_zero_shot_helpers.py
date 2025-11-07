import json
import os
import base64
import types
import importlib

import pytest

from lambda_handlers.llm import zero_shot as zs


def test_normalize_base_url_strips_trailing_and_v1():
    assert zs._normalize_base_url("http://host/") == "http://host"
    assert zs._normalize_base_url("http://host/v1") == "http://host"
    assert zs._normalize_base_url("http://host/api") == "http://host/api"


def test_parse_json_from_text_variants():
    # Strict JSON
    assert zs._parse_json_from_text('{"intent":"a","entities":{}}') == {"intent": "a", "entities": {}}
    # With extra text around JSON
    mixed = "Here you go: {\"intent\":\"b\",\"entities\":{\"x\":null}} Thanks!"
    assert zs._parse_json_from_text(mixed) == {"intent": "b", "entities": {"x": None}}
    # Completely invalid
    assert zs._parse_json_from_text("not-json") == {"intent": None, "entities": {}}


def test_render_prompt_includes_intents_and_entities(tmp_path, monkeypatch):
    # Use the real template file from package; ensure lists render
    prompt = zs._render_prompt(["order_status", "cancel"], ["order_id", "email"])
    assert "order_status" in prompt and "cancel" in prompt
    assert "order_id" in prompt and "email" in prompt


def test_get_body_variants_json_string_and_base64():
    body = {"text": "hi"}
    event_json = {"body": json.dumps(body)}
    assert zs._get_body(event_json) == body

    b64 = base64.b64encode(json.dumps(body).encode()).decode()
    event_b64 = {"body": b64, "isBase64Encoded": True}
    assert zs._get_body(event_b64) == body

    # Direct invoke (no 'body' key)
    assert zs._get_body(body) == body


def test_classify_uses_langchain_when_available(monkeypatch):
    captured = {}

    def fake_call_with_langchain(system_prompt, user_text, base_url, api_key, model_name, temperature, max_tokens):
        captured["base_url"] = base_url
        return {"intent": "x", "entities": {}}

    # Ensure fallback is NOT called
    monkeypatch.setattr(zs, "_call_with_langchain", fake_call_with_langchain)
    monkeypatch.setattr(zs, "_call_chat_completions_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call http")))

    os.environ["LLM_BASE_URL"] = "http://example.com/v1"
    os.environ["LLM_API_KEY"] = "k"
    os.environ["LLM_MODEL_NAME"] = "m"

    res = zs._classify_zero_shot("hello", ["i"], ["e"])
    assert res == {"intent": "x", "entities": {}}
    # Should strip /v1 when passing to LangChain
    assert captured["base_url"] == "http://example.com"


def test_http_call_retries_and_parses(monkeypatch):
    # Simulate two failures then success
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
        def read(self):
            return json.dumps(self._payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        # On third attempt, return content with JSON string inside message
        payload = {
            "choices": [
                {"message": {"content": '{"intent":"ok","entities":{"x":null}}'}}
            ]
        }
        return FakeResp(payload)

    monkeypatch.setattr(zs, "_normalize_base_url", lambda u: u.rstrip("/"))
    monkeypatch.setattr(zs.json, "loads", json.loads)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = zs._call_chat_completions_http("sys", "hi", "http://h", "", "m", 0.0, 10)
    assert res == {"intent": "ok", "entities": {"x": None}}
    assert calls["n"] == 3


def test_http_call_fails_after_retries(monkeypatch):
    def always_fail(req, timeout):
        raise RuntimeError("nope")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", always_fail)

    with pytest.raises(RuntimeError):
        zs._call_chat_completions_http("sys", "hi", "http://h", "", "m", 0.0, 10)