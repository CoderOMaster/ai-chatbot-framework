from datetime import datetime
from typing import Dict, Any

import pytest
from pydantic import ValidationError

from app.admin.chatlogs import schemas


def test_chatmessage_context_default_isolated() -> None:
    """Ensure each ChatMessage gets a unique default context dictionary."""

    first = schemas.ChatMessage(text="Hello")
    second = schemas.ChatMessage(text="World")

    first.context["foo"] = "bar"

    assert second.context == {}
    assert isinstance(first.context, dict)
    assert isinstance(second.context, dict)


def test_chatmessage_context_rejects_invalid_type() -> None:
    """ValidationError should be raised when context is not a mapping."""

    with pytest.raises(ValidationError) as exc_info:
        schemas.ChatMessage(text="Hi", context="not-a-dict")  # type: ignore[arg-type]

    assert "Input should be a valid dictionary" in str(exc_info.value)


def test_chatthreadinfo_requires_thread_id_and_date() -> None:
    """ChatThreadInfo should serialize and validate required metadata."""

    now = datetime.utcnow()
    thread = schemas.ChatThreadInfo(thread_id="thread-1", date=now)

    assert thread.thread_id == "thread-1"
    assert thread.date == now


def test_botmessage_text_is_required() -> None:
    """BotMessage must contain text, and missing text raises ValidationError."""

    with pytest.raises(ValidationError) as exc_info:
        schemas.BotMessage(text=None)  # type: ignore[arg-type]

    assert "Input should be a valid string" in str(exc_info.value)


def test_chatlog_accepts_multiple_bot_messages() -> None:
    """ChatLog should accept a list of BotMessage models for the conversation."""

    user_msg = schemas.ChatMessage(text="Hi")
    bot_messages = [schemas.BotMessage(text="Hello"), schemas.BotMessage(text="How can I help?")]
    log = schemas.ChatLog(
        user_message=user_msg,
        bot_message=bot_messages,
        date=datetime.utcnow(),
    )

    assert log.user_message.text == "Hi"
    assert len(log.bot_message) == 2
    assert [message.text for message in log.bot_message] == ["Hello", "How can I help?"]


def test_chatlog_context_default_factory_independent() -> None:
    """ChatLog context should default to a new mapping per instance."""

    log_one = schemas.ChatLog(
        user_message=schemas.ChatMessage(text="First"),
        bot_message=[schemas.BotMessage(text="Reply")],
        date=datetime.utcnow(),
    )
    log_two = schemas.ChatLog(
        user_message=schemas.ChatMessage(text="Second"),
        bot_message=[schemas.BotMessage(text="Reply")],
        date=datetime.utcnow(),
    )

    log_one.context["state"] = "first"
    assert log_two.context == {}
    assert log_one.context["state"] == "first"


def test_chatlog_context_rejects_invalid_type() -> None:
    """Non-dict context on ChatLog should fail validation."""

    with pytest.raises(ValidationError) as exc_info:
        schemas.ChatLog(
            user_message=schemas.ChatMessage(text="Hi"),
            bot_message=[schemas.BotMessage(text="Bot reply")],
            date=datetime.utcnow(),
            context="should-be-dict",  # type: ignore[arg-type]
        )

    assert "Input should be a valid dictionary" in str(exc_info.value)


def test_chatlogresponse_serialization_round_trip() -> None:
    """ChatLogResponse should retain pagination metadata and conversation list."""

    conversations = [
        schemas.ChatThreadInfo(thread_id="1", date=datetime.utcnow()),
        schemas.ChatThreadInfo(thread_id="2", date=datetime.utcnow()),
    ]
    response = schemas.ChatLogResponse(total=2, page=1, limit=10, conversations=conversations)

    serialized: Dict[str, Any] = response.model_dump()

    assert serialized["total"] == 2
    assert serialized["page"] == 1
    assert serialized["limit"] == 10
    assert isinstance(serialized["conversations"], list)
    assert serialized["conversations"][0]["thread_id"] == "1"


def test_chatlogresponse_requires_pagination_values() -> None:
    """Missing pagination fields should cause validation failure."""

    with pytest.raises(ValidationError):
        schemas.ChatLogResponse(total=1, page=1, limit=10, conversations=None)  # type: ignore[arg-type]



def test_chatlogresponse_conversations_must_be_list() -> None:
    """Enforcing that conversations is a list of ChatThreadInfo models."""

    with pytest.raises(ValidationError):
        schemas.ChatLogResponse(total=0, page=1, limit=5, conversations="invalid")  # type: ignore[arg-type]