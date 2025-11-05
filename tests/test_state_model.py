from datetime import datetime, timezone, timedelta
import pytest
from app.bot.memory.models import State


class DummyUserMessage:
    def __init__(self, text, context=None):
        self.text = text
        self.context = context or {}

    def to_dict(self):
        return {"text": self.text, "context": self.context}


def test_state_defaults_and_to_from_dict():
    s = State(thread_id="t1")
    assert s.thread_id == "t1"
    assert s.context == {}
    assert s.parameters == []
    assert isinstance(s.date, datetime)
    assert s.date.tzinfo == timezone.utc

    d = s.to_dict()
    assert d["thread_id"] == "t1"
    assert d["user_message"] is None

    # from_dict should recreate the State with provided values
    now = datetime.now(timezone.utc)
    s2 = State.from_dict({
        "thread_id": "t1",
        "context": {"k": "v"},
        "parameters": [{"p": 1}],
        "extracted_parameters": {"a": 1},
        "missing_parameters": ["m"],
        "complete": True,
        "current_node": "n",
        "date": now,
    })

    assert s2.thread_id == "t1"
    assert s2.context == {"k": "v"}
    assert s2.parameters == [{"p": 1}]
    assert s2.extracted_parameters == {"a": 1}
    assert s2.missing_parameters == ["m"]
    assert s2.complete is True
    assert s2.current_node == "n"
    assert s2.date == now


def test_update_resets_on_complete():
    s = State(thread_id="t2", complete=True, current_node="node1")
    um = DummyUserMessage("hi", context={"a": 1})

    s.update(um)
    assert s.user_message is um
    assert s.context.get("a") == 1
    assert s.complete is False
    assert s.bot_message == []
    assert s.intent is None
    assert s.parameters == []
    assert s.extracted_parameters == {}
    assert s.missing_parameters == []
    assert s.current_node is None


def test_get_active_intent_id():
    s = State(thread_id="t3", intent={"id": "intent_1"})
    assert s.get_active_intent_id() == "intent_1"

    s2 = State(thread_id="t4")
    assert s2.get_active_intent_id() is None