import json
import os
import importlib.util
from unittest import mock

import pytest

TEST_DIR = os.path.dirname(__file__)
ZERO_SHOT_PATH = os.path.join(TEST_DIR, os.pardir, "lambda", "handlers", "llm", "zero_shot.py")
ZERO_SHOT_PATH = os.path.normpath(ZERO_SHOT_PATH)


def _load_module():
    spec = importlib.util.spec_from_file_location("llm_zero_shot", ZERO_SHOT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_handler_returns_400_on_missing_text():
    module = _load_module()
    res = module.handler({}, None)
    assert res["statusCode"] == 400
    body = json.loads(res["body"])
    assert "error" in body


def test_handler_returns_200_with_parsed_body(monkeypatch):
    module = _load_module()

    expected = {"intent": "greet", "entities": {"name": "Bob"}}

    monkeypatch.setattr(module, "_call_llm", lambda text, intents, entities: expected)

    event = {"text": "hello", "intents": ["greet"], "entities": ["name"]}
    res = module.handler(event, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body == expected


def test_handler_returns_502_on_call_failure(monkeypatch):
    module = _load_module()

    def raise_err(text, intents, entities):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_call_llm", raise_err)

    event = {"text": "hi"}
    res = module.handler(event, None)
    assert res["statusCode"] == 502
    body = json.loads(res["body"])
    assert "error" in body and "LLM call failed" in body.get("error", "") or "details" in body


def test__build_prompt_renders_intents_and_entities():
    module = _load_module()
    prompt = module._build_prompt("hello", intents=["greet"], entities=["name"])
    assert "greet" in prompt
    assert "name" in prompt


def test__call_llm_parses_chat_choice_message(monkeypatch):
    module = _load_module()

    expected = {"intent": "greet", "entities": {"name": "Eve"}}
    content = json.dumps(expected)

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    class MockSession:
        def post(self, *a, **k):
            return MockResponse()

    monkeypatch.setattr(module, "_requests_session_with_retries", lambda: MockSession())

    out = module._call_llm("hi", intents=["greet"], entities=["name"])
    assert out["intent"] == "greet"
    assert out["entities"]["name"] == "Eve"


def test__call_llm_raises_on_no_content(monkeypatch):
    module = _load_module()

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class MockSession:
        def post(self, *a, **k):
            return MockResponse()

    monkeypatch.setattr(module, "_requests_session_with_retries", lambda: MockSession())

    with pytest.raises(ValueError):
        module._call_llm("hi", intents=None, entities=None)