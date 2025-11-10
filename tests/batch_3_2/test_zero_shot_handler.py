import os
import json
import sys
import types
from types import SimpleNamespace

# Provide a minimal jinja2 shim if not installed to allow importing the handler module
if "jinja2" not in sys.modules:
    class _DummyJinja2(types.SimpleNamespace):
        class Environment:
            def __init__(self, loader=None):
                self.loader = loader
            def get_template(self, name):
                class _T:
                    def render(self, ctx):
                        return "system prompt"
                return _T()
        class FileSystemLoader:
            def __init__(self, path):
                self.path = path
    sys.modules["jinja2"] = _DummyJinja2()

from lambda.handlers.llm import zero_shot as handler_mod


class FakeChain:
    def __init__(self, behaviors):
        # behaviors: list of call outcomes; either Exception() or dict result
        self.behaviors = list(behaviors)
        self.calls = 0

    def invoke(self, payload):
        self.calls += 1
        if not self.behaviors:
            raise RuntimeError("No behaviors configured")
        outcome = self.behaviors.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_missing_text_returns_400(monkeypatch):
    monkeypatch.setenv("RETRY_ATTEMPTS", "1")
    event = {"body": json.dumps({"intents": ["greet"], "entities": ["name"]})}
    resp = handler_mod.handler(event, None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]).get("error") == "Missing 'text' in request"


def test_success_with_body_dict_and_entity_filtering(monkeypatch):
    # Patch _build_chain to avoid importing heavy libs
    fc = FakeChain([
        {"intent": "greet", "entities": {"name": "Alice", "age": None}},
    ])
    monkeypatch.setattr(handler_mod, "_build_chain", lambda intents, entities: fc)

    event = {
        "body": {
            "text": "hello",
            "intents": ["greet"],
            "entities": ["name", "age"],
        }
    }
    resp = handler_mod.handler(event, SimpleNamespace())
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"intent": "greet", "entities": {"name": "Alice"}}
    assert fc.calls == 1


def test_retries_then_success(monkeypatch):
    monkeypatch.setenv("RETRY_ATTEMPTS", "3")
    fc = FakeChain([
        Exception("temp failure"),
        Exception("temp failure 2"),
        {"intent": "bye", "entities": {}},
    ])
    monkeypatch.setattr(handler_mod, "_build_chain", lambda intents, entities: fc)

    event = {"body": json.dumps({"text": "cya"})}
    resp = handler_mod.handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"intent": "bye", "entities": {}}
    assert fc.calls == 3


def test_all_retries_fail_returns_502(monkeypatch):
    monkeypatch.setenv("RETRY_ATTEMPTS", "2")
    fc = FakeChain([Exception("boom1"), Exception("boom2")])
    monkeypatch.setattr(handler_mod, "_build_chain", lambda intents, entities: fc)

    event = {"body": json.dumps({"text": "hi"})}
    resp = handler_mod.handler(event, None)
    assert resp["statusCode"] == 502
    body = json.loads(resp["body"]) 
    assert body["error"] == "LLM invocation failed"
    assert "boom2" in body["details"]
    assert fc.calls == 2


def test_initialization_failure_returns_500(monkeypatch):
    def boom(intents, entities):
        raise RuntimeError("LangChain/OpenAI libs not available. Ensure layer is attached.")
    monkeypatch.setattr(handler_mod, "_build_chain", boom)

    event = {"body": json.dumps({"text": "hi"})}
    resp = handler_mod.handler(event, None)
    assert resp["statusCode"] == 500
    msg = json.loads(resp["body"]).get("error")
    assert "LangChain/OpenAI libs not available" in msg


def test_invalid_json_string_body_results_in_400(monkeypatch):
    # invalid JSON becomes {}, then missing text -> 400
    event = {"body": "{not json}"}
    resp = handler_mod.handler(event, None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]).get("error") == "Missing 'text' in request"


def test_event_without_body_uses_event_payload(monkeypatch):
    fc = FakeChain([
        {"intent": "greet", "entities": {}}
    ])
    monkeypatch.setattr(handler_mod, "_build_chain", lambda intents, entities: fc)

    event = {"text": "hello"}
    resp = handler_mod.handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"intent": "greet", "entities": {}}
    assert fc.calls == 1