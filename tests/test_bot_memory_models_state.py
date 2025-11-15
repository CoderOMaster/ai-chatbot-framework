import pytest
from datetime import datetime, UTC

from app.bot.memory.models import State


class DummyUserMessage:
    def __init__(self, text="hi", context=None):
        self.text = text
        self.context = context or {}

    def to_dict(self):
        return {"text": self.text, "context": self.context}


def test_state_defaults_and_to_dict():
    s = State(thread_id="t1")
    d = s.to_dict()

    assert d["thread_id"] == "t1"
    assert d["user_message"] is None
    assert d["bot_message"] is None
    assert d["context"] == {}
    assert d["intent"] == {}
    assert d["parameters"] == []
    assert d["extracted_parameters"] == {}
    assert d["missing_parameters"] == []
    assert d["complete"] is False
    assert d["current_node"] == ""
    assert isinstance(d["date"], datetime)
    assert d["nlu"] == {}


def test_state_from_dict_partial():
    s = State.from_dict({
        "thread_id": "t2",
        "context": {"foo": 1},
        "intent": {"id": "greet"},
        "parameters": [
            {"name": "p1"}
        ],
        "extracted_parameters": {"p": 1},
        "missing_parameters": ["x"],
        "complete": True,
        "current_node": "n1",
    })
    assert s.thread_id == "t2"
    assert s.context == {"foo": 1}
    assert s.intent == {"id": "greet"}
    assert s.parameters == [{"name": "p1"}]
    assert s.extracted_parameters == {"p": 1}
    assert s.missing_parameters == ["x"]
    assert s.complete is True
    assert s.current_node == "n1"


def test_state_update_sets_user_message_and_resets_when_complete():
    s = State(thread_id="t3", complete=True, bot_message=[{"text": "done"}], intent={"id": "bye"}, parameters=[{"a": 1}], extracted_parameters={"a": 1}, missing_parameters=["a"], current_node="node")
    msg = DummyUserMessage(text="hello", context={"k": "v"})

    s.update(msg)

    assert s.user_message is msg
    assert isinstance(s.date, datetime)
    # Context merges
    assert s.context["k"] == "v"
    # Because it was complete=True, update should reset fields
    assert s.bot_message == []
    assert s.intent is None
    assert s.parameters == []
    assert s.extracted_parameters == {}
    assert s.missing_parameters == []
    assert s.complete is False
    assert s.current_node is None


def test_get_active_intent_id():
    s = State(thread_id="t4")
    assert s.get_active_intent_id() is None
    s.intent = {"id": "greet"}
    assert s.get_active_intent_id() == "greet"


def test_user_message_serialization_in_to_dict():
    s = State(thread_id="t5", user_message=DummyUserMessage(text="hey"))
    d = s.to_dict()
    assert d["user_message"] == {"text": "hey", "context": {}}