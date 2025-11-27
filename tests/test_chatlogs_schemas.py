import pytest
from datetime import datetime
from pydantic import ValidationError

from app.admin.chatlogs import schemas


@pytest.fixture
def now() -> datetime:
    """Return a consistent current datetime for tests."""
    return datetime.utcnow()


def test_chatmessage_defaults_and_independence() -> None:
    """ChatMessage should default context to a new empty dict per instance."""
    a = schemas.ChatMessage(text="hello")
    assert a.text == "hello"
    assert isinstance(a.context, dict)
    assert a.context == {}

    # Mutating one instance's context should not affect another
    a.context['x'] = 1
    b = schemas.ChatMessage(text="other")
    assert b.context == {}


def test_chatmessage_with_context() -> None:
    """Provided context should be preserved."""
    ctx = {"k": "v"}
    m = schemas.ChatMessage(text="hi", context=ctx)
    assert m.context == ctx


def test_chatmessage_missing_text_raises() -> None:
    """text is required for ChatMessage; missing should raise ValidationError."""
    with pytest.raises(ValidationError):
        schemas.ChatMessage()  # type: ignore[arg-type]


def test_chatthreadinfo_valid_date(now: datetime) -> None:
    """ChatThreadInfo accepts datetime for date field."""
    t = schemas.ChatThreadInfo(thread_id="thread-1", date=now)
    assert t.thread_id == "thread-1"
    assert t.date == now


def test_chatthreadinfo_invalid_date_raises() -> None:
    """Non-datetime date should raise ValidationError."""
    with pytest.raises(ValidationError):
        schemas.ChatThreadInfo(thread_id="t", date="2020-01-01")


def test_botmessage_basic() -> None:
    """BotMessage holds simple text responses."""
    b = schemas.BotMessage(text="ok")
    assert b.text == "ok"


def test_chatlog_valid_and_context_default_independence(now: datetime) -> None:
    """ChatLog should parse nested models and default context should be isolated."""
    user = schemas.ChatMessage(text="u")
    bots = [schemas.BotMessage(text="b1")]
    l1 = schemas.ChatLog(user_message=user, bot_message=bots, date=now)
    assert l1.user_message.text == "u"
    assert isinstance(l1.bot_message, list)
    assert l1.context == {}

    # Mutate context and ensure another instance has fresh default
    l1.context['a'] = 123
    l2 = schemas.ChatLog(user_message=user, bot_message=bots, date=now)
    assert l2.context == {}


def test_chatlog_invalid_date_raises(now: datetime) -> None:
    """ChatLog should reject non-datetime date values."""
    user = schemas.ChatMessage(text="u")
    bots = [schemas.BotMessage(text="b1")]
    with pytest.raises(ValidationError):
        schemas.ChatLog(user_message=user, bot_message=bots, date="bad-date")


def test_chatlog_bot_message_accepts_dicts_and_parses(now: datetime) -> None:
    """bot_message list may contain dicts which should be coerced to BotMessage."""
    user = {"text": "u"}
    bots = [{"text": "b1"}, {"text": "b2"}]
    log = schemas.ChatLog(user_message=user, bot_message=bots, date=now)
    assert len(log.bot_message) == 2
    assert all(isinstance(b, schemas.BotMessage) for b in log.bot_message)
    assert log.user_message.text == "u"


def test_chatloglistview_preview_length_enforced(now: datetime) -> None:
    """user_message_preview must not exceed max_length=100."""
    short = "x" * 100
    view = schemas.ChatLogListView(thread_id="t", date=now, user_message_preview=short)
    assert view.user_message_preview == short

    long_preview = "y" * 101
    with pytest.raises(ValidationError):
        schemas.ChatLogListView(thread_id="t", date=now, user_message_preview=long_preview)


def test_chatloglistview_invalid_date_raises() -> None:
    """ChatLogListView should validate date field type."""
    with pytest.raises(ValidationError):
        schemas.ChatLogListView(thread_id="t", date="not-a-date", user_message_preview="p")


def test_chatlogdetailview_valid_and_context_default(now: datetime) -> None:
    """ChatLogDetailView should include full nested data and default context."""
    user = {"text": "hello"}
    bots = [{"text": "b1"}]
    detail = schemas.ChatLogDetailView(thread_id="th", user_message=user, bot_message=bots, date=now)
    assert detail.thread_id == "th"
    assert isinstance(detail.user_message, schemas.ChatMessage)
    assert isinstance(detail.bot_message[0], schemas.BotMessage)
    assert detail.context == {}


def test_chatlogdetailview_invalid_date_raises() -> None:
    """ChatLogDetailView should reject invalid date types."""
    with pytest.raises(ValidationError):
        schemas.ChatLogDetailView(thread_id="t", user_message={"text": "u"}, bot_message=[{"text": "b"}], date=123)


def test_chatlogresponse_with_conversations_parsing(now: datetime) -> None:
    """ChatLogResponse should accept a list of ChatThreadInfo items or dicts and coerce them."""
    conv1 = {"thread_id": "t1", "date": now}
    conv2 = schemas.ChatThreadInfo(thread_id="t2", date=now)
    resp = schemas.ChatLogResponse(total=2, page=1, limit=10, conversations=[conv1, conv2])
    assert resp.total == 2
    assert resp.page == 1
    assert resp.limit == 10
    assert len(resp.conversations) == 2
    assert all(isinstance(c, schemas.ChatThreadInfo) for c in resp.conversations)


def test_conversation_missing_required_fields_raises() -> None:
    """Missing required fields for nested conversation items should raise ValidationError."""
    with pytest.raises(ValidationError):
        schemas.ChatLogResponse(total=1, page=1, limit=10, conversations=[{"date": datetime.utcnow()}])