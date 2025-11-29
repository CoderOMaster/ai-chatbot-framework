"""Tests for the conversation State model stored by memory services."""

from datetime import datetime as real_datetime, UTC
from typing import Any, Dict

import pytest

from app.bot.dialogue_manager.models import UserMessage
from app.bot.memory import models
from app.bot.memory.models import State


class DummyDateTime:
    """Helper mimicking the limited datetime API that the module consumes."""

    FIXED: real_datetime = real_datetime(2000, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> real_datetime:
        return cls.FIXED

    @staticmethod
    def fromisoformat(value: str) -> real_datetime:
        return real_datetime.fromisoformat(value)


@pytest.fixture
def base_user_message() -> UserMessage:
    """Return a canonical user message reused across state tests."""

    return UserMessage(
        thread_id="thread-1",
        text="Hello there",
        context={"foo": "bar"},
    )


@pytest.fixture
def legacy_state_payload() -> Dict[str, Any]:
    """Provide an older serialized State payload used by legacy memory services."""

    return {
        "thread_id": "legacy-thread",
        "user_message": {
            "thread_id": "legacy-thread",
            "text": "Legacy hello",
            "context": {"legacy": True},
        },
        "bot_message": [{"text": "legacy response"}],
        "date": "2024-04-01T12:00:00+00:00",
    }


def test_state_to_dict_serializes_user_message(base_user_message: UserMessage) -> None:
    """Verify that State.to_dict flattens a UserMessage into primitives and keeps metadata."""

    custom_date = real_datetime(2024, 5, 5, 12, 0, tzinfo=UTC)
    state = State(
        thread_id="thread-1",
        user_message=base_user_message,
        bot_message=[{"text": "bot reply"}],
        context={"existing": "value"},
        intent={"id": "intent-1"},
        parameters=[{"name": "param"}],
        extracted_parameters={"param": "value"},
        missing_parameters=["param"],
        complete=True,
        current_node="node-1",
        date=custom_date,
    )
    state.nlu = {"entities": ["entity"]}

    serialized = state.to_dict()

    assert serialized["thread_id"] == "thread-1"
    assert serialized["user_message"] == base_user_message.to_dict()
    assert serialized["bot_message"] == [{"text": "bot reply"}]
    assert serialized["nlu"] == {"entities": ["entity"]}
    assert serialized["context"] == {"existing": "value"}
    assert serialized["date"] == custom_date
    assert serialized["complete"] is True


def test_state_from_dict_rehydrates_legacy_payload_with_defaults(
    legacy_state_payload: Dict[str, Any]
) -> None:
    """Ensure from_dict handles legacy dict payloads while supplying missing defaults."""

    state = State.from_dict(legacy_state_payload)

    assert state.thread_id == "legacy-thread"
    assert state.user_message is not None
    assert state.user_message.text == "Legacy hello"
    assert state.context == {}
    assert state.intent == {}
    assert state.parameters == []
    assert state.missing_parameters == []
    assert state.bot_message == [{"text": "legacy response"}]
    assert state.nlu == {}
    assert state.date == real_datetime.fromisoformat(legacy_state_payload["date"])


def test_state_from_dict_preserves_explicit_fields() -> None:
    """Validate that explicit nlu/context/intent/payload fields survive hydration."""

    payload: Dict[str, Any] = {
        "thread_id": "thread-2",
        "user_message": {
            "thread_id": "thread-2",
            "text": "latest hello",
            "context": {"role": "user"},
            "channel": "rest",
        },
        "bot_message": [{"text": "response"}],
        "nlu": {"entities": ["entity"]},
        "context": {"existing": "value"},
        "intent": {"id": "intent-2"},
        "parameters": [{"name": "param"}],
        "extracted_parameters": {"param": "value"},
        "missing_parameters": ["param"],
        "complete": True,
        "current_node": "node-2",
        "date": "2024-07-01T12:30:00+00:00",
    }

    state = State.from_dict(payload)

    assert state.thread_id == payload["thread_id"]
    assert state.user_message.text == payload["user_message"]["text"]
    assert state.bot_message == payload["bot_message"]
    assert state.nlu == payload["nlu"]
    assert state.context == payload["context"]
    assert state.intent == payload["intent"]
    assert state.parameters == payload["parameters"]
    assert state.extracted_parameters == payload["extracted_parameters"]
    assert state.missing_parameters == payload["missing_parameters"]
    assert state.complete is True
    assert state.current_node == "node-2"
    assert state.date == real_datetime.fromisoformat(payload["date"])


def test_deserialize_user_message_accepts_existing_instance(base_user_message: UserMessage) -> None:
    """The helper should return UserMessage instances untouched."""

    deserialized = State._deserialize_user_message(base_user_message)

    assert deserialized is base_user_message


def test_deserialize_user_message_parses_dict_payload(base_user_message: UserMessage) -> None:
    """Dict payloads should be converted into UserMessage objects."""

    payload = base_user_message.to_dict()
    deserialized = State._deserialize_user_message(payload)

    assert isinstance(deserialized, UserMessage)
    assert deserialized.thread_id == base_user_message.thread_id
    assert deserialized.text == base_user_message.text
    assert deserialized.context == base_user_message.context


def test_deserialize_user_message_returns_none_for_unknown_payload() -> None:
    """Unexpected payloads should not raise but should return None."""

    assert State._deserialize_user_message("raw-string") is None


def test_normalize_date_returns_existing_datetime() -> None:
    """Providing a datetime should bypass any conversion logic."""

    original = real_datetime(2024, 6, 1, 13, 0, tzinfo=UTC)

    assert State._normalize_date(original) == original


def test_normalize_date_parses_iso_string() -> None:
    """ISO-formatted strings should be converted into datetime representations."""

    iso_value = "2024-07-01T14:15:00+00:00"

    assert State._normalize_date(iso_value) == real_datetime.fromisoformat(iso_value)


def test_normalize_date_handles_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid or missing dates fall back to the current timestamp that memory controls."""

    fallback = real_datetime(2025, 1, 1, tzinfo=UTC)
    DummyDateTime.FIXED = fallback
    monkeypatch.setattr(models, "datetime", DummyDateTime)

    assert State._normalize_date("not-a-date") == fallback
    assert State._normalize_date(None) == fallback


def test_state_update_merges_context_and_updates_date(
    monkeypatch: pytest.MonkeyPatch, base_user_message: UserMessage
) -> None:
    """Updating the state should refresh timestamps and merge in incoming context."""

    fallback = real_datetime(2025, 2, 3, 4, 5, tzinfo=UTC)
    DummyDateTime.FIXED = fallback
    monkeypatch.setattr(models, "datetime", DummyDateTime)

    state = State(thread_id=base_user_message.thread_id, context={"existing": "value"})
    new_message = UserMessage(
        thread_id=base_user_message.thread_id,
        text="Updated text",
        context={"new": "value"},
    )

    state.update(new_message)

    assert state.user_message is new_message
    assert state.context == {"existing": "value", "new": "value"}
    assert state.date == fallback


def test_state_update_resets_tracking_when_complete(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once a State is marked complete, update should zero-out intent tracking metadata."""

    fallback = real_datetime(2026, 3, 4, 5, 6, tzinfo=UTC)
    DummyDateTime.FIXED = fallback
    monkeypatch.setattr(models, "datetime", DummyDateTime)

    state = State(thread_id="thread-3", bot_message=[{"text": "old"}], context={"keep": "value"})
    state.complete = True
    state.intent = {"id": "reset"}
    state.parameters = [{"name": "param"}]
    state.extracted_parameters = {"param": "value"}
    state.missing_parameters = ["param"]
    state.current_node = "node-old"

    new_message = UserMessage(thread_id="thread-3", text="Next", context={"new": "entry"})

    state.update(new_message)

    assert state.user_message is new_message
    assert state.bot_message == []
    assert state.intent is None
    assert state.parameters == []
    assert state.extracted_parameters == {}
    assert state.missing_parameters == []
    assert state.complete is False
    assert state.current_node is None
    assert state.date == fallback


def test_get_active_intent_id_returns_identifier() -> None:
    """Should surface the identifier stored on State.intent when present."""

    state = State(thread_id="thread-4", intent={"id": "intent-99"})

    assert state.get_active_intent_id() == "intent-99"


def test_get_active_intent_id_returns_none_when_missing() -> None:
    """Should return None when no intent identifier is stored."""

    state = State(thread_id="thread-5")

    assert state.get_active_intent_id() is None