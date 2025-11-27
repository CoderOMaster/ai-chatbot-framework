import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import FrozenInstanceError

from app.bot.memory import models


class DummyUserMessage:
    """A simple stand-in for the real UserMessage used in tests."""
    def __init__(self, text: str = "", context: dict = None):
        self.text = text
        self.context = context or {}

    def to_dict(self) -> dict:
        return {"text": self.text, "context": self.context}

    @classmethod
    def from_dict(cls, data: dict):
        # Simulate minimal validation similar to real implementation
        if not isinstance(data, dict):
            raise TypeError("Invalid user_message data")
        return cls(text=data.get("text", ""), context=data.get("context"))


@pytest.fixture(autouse=True)
def patch_usermessage(monkeypatch):
    """Patch the UserMessage in the module under test to use DummyUserMessage.

    This ensures isinstance checks and from_dict/to_dict behavior are
    predictable for tests.
    """
    monkeypatch.setattr(models, "UserMessage", DummyUserMessage)
    yield


def test_state_post_init_invalid_thread_id_raises():
    """State with empty thread_id should raise StateValidationError in __post_init__."""
    with pytest.raises(models.StateValidationError):
        models.State(thread_id="")


def test_state_date_default_set():
    """If date is not provided, it should be populated with a datetime value."""
    s = models.State(thread_id="t1")
    assert isinstance(s.date, datetime)
    # date should be recent (within a few seconds)
    assert datetime.now(timezone.utc) - s.date < timedelta(seconds=5)


def test_to_dict_includes_user_message_to_dict():
    """to_dict should call user_message.to_dict() when user_message is present."""
    um = DummyUserMessage(text="hello", context={"k": "v"})
    s = models.State(thread_id="t2", user_message=um, bot_message=[{"msg": "ok"}])
    d = s.to_dict()
    assert d["thread_id"] == "t2"
    assert d["user_message"] == {"text": "hello", "context": {"k": "v"}}
    assert d["bot_message"] == [{"msg": "ok"}]


def test_from_dict_success_with_user_message():
    """from_dict should deserialize a nested user_message via UserMessage.from_dict."""
    payload = {
        "thread_id": "t3",
        "user_message": {"text": "hey", "context": {"a": 1}},
        "bot_message": [{"m": 1}],
        "version": 2,
    }
    state = models.State.from_dict(payload)
    assert isinstance(state, models.State)
    assert state.thread_id == "t3"
    assert isinstance(state.user_message, DummyUserMessage)
    assert state.user_message.text == "hey"
    assert state.version == 2


def test_from_dict_missing_thread_id_raises():
    """from_dict should raise StateValidationError if required fields missing."""
    with pytest.raises(models.StateValidationError) as exc:
        models.State.from_dict({"user_message": {"text": "x"}})
    assert "Missing required fields" in str(exc.value)


def test_from_dict_user_message_deserialize_error_raises(monkeypatch):
    """If UserMessage.from_dict raises (TypeError/ValueError) it should be wrapped in StateValidationError."""
    def bad_from_dict(_):
        raise TypeError("bad user_message")

    monkeypatch.setattr(models, "UserMessage", DummyUserMessage)
    monkeypatch.setattr(models.UserMessage, "from_dict", staticmethod(bad_from_dict))

    with pytest.raises(models.StateValidationError) as exc:
        models.State.from_dict({"thread_id": "t4", "user_message": {"text": "x"}})
    assert "Failed to deserialize state" in str(exc.value)


def test_update_with_invalid_user_message_type_raises():
    """update should raise StateTransitionError when provided a non-UserMessage instance."""
    s = models.State(thread_id="t5")
    with pytest.raises(models.StateTransitionError):
        s.update(user_message={"not": "a UserMessage"})


def test_update_creates_new_state_and_merges_context():
    """update returns a new State with merged context and updated date without mutating original."""
    original = models.State(thread_id="t6", context={"x": 1}, bot_message=[{"m": 1}])
    um = DummyUserMessage(text="hi", context={"y": 2})

    new_state = original.update(um)

    # Original remains unchanged
    assert original.user_message is None
    assert original.context == {"x": 1}

    # New has updated user_message and merged context
    assert new_state.user_message is um
    assert new_state.context == {"x": 1, "y": 2}
    assert new_state is not original
    assert new_state.date != original.date


def test_update_resets_fields_when_complete_true():
    """When state.complete is True, update should reset completion-related fields on the new instance."""
    s = models.State(
        thread_id="t7",
        complete=True,
        bot_message=[{"old": True}],
        intent={"id": "i1"},
        parameters=[{"p": 1}],
        extracted_parameters={"e": 2},
        missing_parameters=["m1"],
        current_node="n1",
    )
    um = DummyUserMessage(text="restart")
    new = s.update(um)

    assert new.complete is False
    assert new.bot_message == []
    assert new.intent == {}
    assert new.parameters == []
    assert new.extracted_parameters == {}
    assert new.missing_parameters == []
    assert new.current_node == ""


def test_get_active_intent_id_behaviour():
    """get_active_intent_id should return None when no intent and the id when present."""
    s = models.State(thread_id="t8", intent={})
    assert s.get_active_intent_id() is None
    s2 = models.State(thread_id="t9", intent={"id": "intent_123"})
    assert s2.get_active_intent_id() == "intent_123"


def test_state_is_frozen_immutable_assignment_raises():
    """State dataclass should be frozen; attempts to set attributes should raise FrozenInstanceError."""
    s = models.State(thread_id="t10")
    with pytest.raises(FrozenInstanceError):
        s.thread_id = "other"


def test_versioning_set_from_dict_and_default():
    """Verify version defaults to 1 and can be set via from_dict."""
    s_default = models.State(thread_id="t11")
    assert s_default.version == 1

    s = models.State.from_dict({"thread_id": "t12", "version": 5})
    assert s.version == 5