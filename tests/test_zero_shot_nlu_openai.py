import json
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from app.bot.nlu.llm import zero_shot_nlu_openai as zs


def test_build_prompt_renders_intents_and_entities():
    prompt = zs._build_prompt("hello", intents=["greet", "bye"], entities=["name"])
    assert "greet" in prompt
    assert "name" in prompt


def test_requests_session_with_retries_has_adapters():
    session = zs._requests_session_with_retries()
    assert isinstance(session, object)
    # adapters for http and https should be mounted
    assert "https://" in session.adapters
    assert "http://" in session.adapters


def test_classify_raises_on_empty_text():
    with pytest.raises(ValueError):
        zs.classify("")


def test_classify_handles_network_error_and_returns_empty(monkeypatch):
    class MockSession:
        def post(self, *args, **kwargs):
            raise RuntimeError("network")

    monkeypatch.setattr(zs, "_requests_session_with_retries", lambda: MockSession())

    out = zs.classify("hi there")
    assert out["intent"] is None
    assert out["intent_ranking"] == []
    assert out["entities"] == {}


def test_classify_parses_openai_chat_choice_message(monkeypatch):
    expected = {"intent": "greet", "entities": {"name": "Alice"}}
    content = json.dumps(expected)

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    class MockSession:
        def __init__(self):
            self.last_call = None

        def post(self, url, json=None, headers=None, timeout=None):
            self.last_call = {"url": url, "json": json, "headers": headers, "timeout": timeout}
            return MockResponse()

    mock_session = MockSession()
    monkeypatch.setattr(zs, "_requests_session_with_retries", lambda: mock_session)

    out = zs.classify("hello world", intents=["greet"], entities=["name"], api_key="secret")
    assert out["intent"]["intent"] == "greet"
    assert out["entities"] == {"name": "Alice"}
    # ensure Authorization header was set
    assert mock_session.last_call["headers"]["Authorization"] == "Bearer secret"


def test_classify_parses_choice_text_variant(monkeypatch):
    expected = {"intent": "bye", "entities": {}}
    content = json.dumps(expected)

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"text": content}]}

    class MockSession:
        def post(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr(zs, "_requests_session_with_retries", lambda: MockSession())

    out = zs.classify("goodbye", intents=["bye"], entities=None)
    assert out["intent"]["intent"] == "bye"


def test_classify_parses_top_level_output(monkeypatch):
    expected = {"intent": "ask", "entities": {"topic": "weather"}}
    content = json.dumps(expected)

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output": content}

    class MockSession:
        def post(self, *a, **k):
            return MockResponse()

    monkeypatch.setattr(zs, "_requests_session_with_retries", lambda: MockSession())

    out = zs.classify("what's the weather?", intents=["ask"], entities=["topic"])
    assert out["intent"]["intent"] == "ask"
    assert out["entities"]["topic"] == "weather"


def test_classify_handles_non_json_content(monkeypatch):
    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not json"}}]}

    class MockSession:
        def post(self, *a, **k):
            return MockResponse()

    monkeypatch.setattr(zs, "_requests_session_with_retries", lambda: MockSession())

    out = zs.classify("blah")
    assert out["intent"] is None


def test_zero_shot_wrapper_process_no_text_returns_message():
    wrapper = zs.ZeroShotNLUOpenAI()
    msg = {"raw": "yes"}
    out = wrapper.process(msg.copy())
    assert out == msg


def test_zero_shot_wrapper_process_calls_classify(monkeypatch):
    wrapper = zs.ZeroShotNLUOpenAI(intents=["greet"], entities=["name"], api_key="k")

    def fake_classify(text, intents, entities, base_url, model_name, api_key, timeout=15):
        return {"intent": {"intent": "greet", "confidence": 1.0}, "intent_ranking": [], "entities": {}}

    monkeypatch.setattr(zs, "classify", fake_classify)

    msg = {"text": "hi"}
    out = wrapper.process(msg)
    assert out["intent"]["intent"] == "greet"
    assert "intent_ranking" in out
    assert "entities" in out