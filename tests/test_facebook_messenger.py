import asyncio
from collections import deque
from datetime import datetime, timedelta
import hashlib
import hmac
from typing import Any, Dict, List

import pytest
from unittest.mock import AsyncMock, Mock

from app.bot.channels.facebook import messenger
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


async def _no_sleep(_=None):
    """Replacement for asyncio.sleep in tests to speed them up."""
    return None


def test_validate_hub_signature_valid_and_invalid():
    """
    Validate that valid signatures return True and malformed/invalid signatures return False.
    """
    secret = "supersecret"
    cfg = {"secret": secret, "page_access_token": "token"}
    receiver = messenger.FacebookReceiver(cfg, dialogue_manager_url="http://dm")

    payload = b"hello-world"
    digest = hmac.new(bytearray(secret, "utf8"), payload, hashlib.sha256).hexdigest()
    header = f"sha256={digest}"

    assert receiver.validate_hub_signature(payload, header) is True

    # Wrong signature
    bad_header = "sha256=deadbeef"
    assert receiver.validate_hub_signature(payload, bad_header) is False

    # Malformed header
    assert receiver.validate_hub_signature(payload, "notvalid") is False


async def test_rate_limiter_cleans_old_entries(monkeypatch):
    """
    Ensure RateLimiter removes old entries outside the window and appends a new timestamp.
    """
    rl = messenger.RateLimiter(max_requests=5, window_seconds=1)

    # Prepopulate with an expired timestamp
    old_time = datetime.now() - timedelta(seconds=2)
    rl.request_times.append(old_time)

    # Patch sleep to no-op to avoid delays if code paths trigger waiting
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    await rl.acquire()

    # After acquire, the old entry should have been removed and a new one appended
    assert len(rl.request_times) == 1
    assert rl.request_times[0] > old_time


async def test_message_deduplicator_detects_and_expires_duplicates():
    """
    Ensure MessageDeduplicator flags duplicates within window and expires them after window.
    """
    dedup = messenger.MessageDeduplicator(window_seconds=1)

    sender_id = "user1"
    text = "hello"
    timestamp = int(datetime.now().timestamp())

    # First message should not be duplicate
    first = await dedup.is_duplicate(sender_id, text, timestamp)
    assert first is False

    # Second immediate message should be considered duplicate
    second = await dedup.is_duplicate(sender_id, text, timestamp)
    assert second is True

    # Simulate expiry by adjusting the stored timestamp to old
    mid = dedup._generate_message_id(sender_id, text, timestamp)
    dedup.seen_messages[mid] = datetime.now() - timedelta(seconds=2)

    third = await dedup.is_duplicate(sender_id, text, timestamp)
    assert third is False


async def test_message_queue_enqueue_dequeue_and_requeue():
    """
    Test enqueuing, dequeuing, and requeue behavior including retry limit.
    """
    mq = messenger.MessageQueue(max_retries=2)

    message = {"text": "hi"}
    await mq.enqueue(message)

    item = await mq.dequeue()
    assert item is not None
    assert item["data"] == message
    assert item["retries"] == 0

    # Requeue once (should succeed)
    requeued = await mq.requeue(item)
    assert requeued is True

    # Dequeue again and requeue twice - second requeue should fail due to max_retries
    item2 = await mq.dequeue()
    assert item2 is not None
    assert item2["retries"] == 1

    requeued2 = await mq.requeue(item2)
    assert requeued2 is True

    item3 = await mq.dequeue()
    assert item3 is not None
    assert item3["retries"] == 2

    # Now requeue should fail because retries == max_retries
    requeued3 = await mq.requeue(item3)
    assert requeued3 is False


class _DummyResponse:
    def __init__(self, status: int, json_data: Any = None, headers: Dict[str, Any] = None):
        self.status = status
        self._json = json_data or {}
        self.headers = headers or {}

    async def json(self):
        return self._json


class _RespCM:
    def __init__(self, response: _DummyResponse):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SessionCM:
    def __init__(self, responses: List[_DummyResponse]):
        # responses is a list that post() will pop from
        self._responses = list(responses)
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        # record call
        self.post_calls.append({"args": args, "kwargs": kwargs})
        if not self._responses:
            # default to 500 error if exhausted
            return _RespCM(_DummyResponse(500, {"error": "no more responses"}))
        resp = self._responses.pop(0)
        return _RespCM(resp)


async def test_facebook_sender_success_and_retry(monkeypatch):
    """
    Test FacebookSender handles success and retry-able server errors (500) and then success.
    """
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    # Prepare responses: first 500, then 200
    responses = [_DummyResponse(500, {"error": "server"}), _DummyResponse(200, {"result": "ok"})]
    session_cm = _SessionCM(responses)

    async def fake_client_session(*args, **kwargs):
        return session_cm

    monkeypatch.setattr(messenger.aiohttp, "ClientSession", fake_client_session)

    sender = messenger.FacebookSender(access_token="token")

    result = await sender.send_message("recipient1", {"text": "hello"})

    assert result == {"result": "ok"}
    # Ensure two post calls were made (one for 500, one for 200)
    assert len(session_cm.post_calls) == 2


async def test_facebook_sender_handles_rate_limit_then_success(monkeypatch):
    """
    Simulate a 429 response with Retry-After header followed by a success.
    """
    # no-op sleep
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    responses = [
        _DummyResponse(429, {"error": "rate limited"}, headers={"Retry-After": "0"}),
        _DummyResponse(200, {"ok": True}),
    ]
    session_cm = _SessionCM(responses)

    async def fake_client_session(*args, **kwargs):
        return session_cm

    monkeypatch.setattr(messenger.aiohttp, "ClientSession", fake_client_session)

    sender = messenger.FacebookSender(access_token="token")

    res = await sender.send_message("r2", {"text": "hi"})
    assert res == {"ok": True}
    assert len(session_cm.post_calls) == 2


async def test_facebook_sender_timeout_raises(monkeypatch):
    """
    Test that persistent timeouts raise an HTTPException with 504 status after retries.
    """
    # Patch sleep to fast no-op
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    class _BadSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            # Simulate raising TimeoutError when attempting to use the context manager
            async def _raiser():
                raise asyncio.TimeoutError()

            # Return an object that will raise on __aenter__
            class _BrokenCM:
                async def __aenter__(self_inner):
                    raise asyncio.TimeoutError()

                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False

            return _BrokenCM()

    async def fake_client_session(*args, **kwargs):
        return _BadSession()

    monkeypatch.setattr(messenger.aiohttp, "ClientSession", fake_client_session)

    sender = messenger.FacebookSender(access_token="token")

    with pytest.raises(HTTPException) as excinfo:
        await sender.send_message("r3", {"text": "will timeout"})

    assert excinfo.value.status_code in (500, 504)


async def test_process_messaging_event_text_and_postback(monkeypatch):
    """
    Ensure process_messaging_event triggers handle_message for text and postback events, and deduplicates duplicates.
    """
    cfg = {"secret": "s", "page_access_token": "t"}
    receiver = messenger.FacebookReceiver(cfg, dialogue_manager_url="http://dm")

    # Patch deduplicator to return False (not duplicate) for first run
    receiver.deduplicator.is_duplicate = AsyncMock(return_value=False)
    receiver.handle_message = AsyncMock()

    # Text message event
    event_text = {"sender": {"id": "u1"}, "message": {"text": "hello"}, "timestamp": 123}
    await receiver.process_messaging_event(event_text, page_id="page1")
    receiver.handle_message.assert_called_once()

    receiver.handle_message.reset_mock()

    # Now simulate duplicate: is_duplicate -> True
    receiver.deduplicator.is_duplicate = AsyncMock(return_value=True)
    await receiver.process_messaging_event(event_text, page_id="page1")
    receiver.handle_message.assert_not_called()

    # Test postback handling when not duplicate
    receiver.deduplicator.is_duplicate = AsyncMock(return_value=False)
    event_postback = {"sender": {"id": "u1"}, "postback": {"payload": "PAY"}, "timestamp": 124}
    await receiver.process_messaging_event(event_postback, page_id="page1")
    assert receiver.handle_message.call_count == 1


async def test_handle_message_calls_dialogue_manager_and_sends(monkeypatch):
    """
    Test that handle_message posts to the dialogue manager and then calls sender.send_message for returned bot messages.
    """
    # Patch sleep
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    cfg = {"secret": "s", "page_access_token": "t"}
    receiver = messenger.FacebookReceiver(cfg, dialogue_manager_url="http://dm")

    # Prepare DM response with bot_message list
    dm_response = _DummyResponse(200, {"bot_message": [{"text": "reply1"}, {"text": "reply2"}]})
    session_cm = _SessionCM([dm_response])

    async def fake_client_session(*args, **kwargs):
        return session_cm

    monkeypatch.setattr(messenger.aiohttp, "ClientSession", fake_client_session)

    # Patch sender.send_message to record calls
    receiver.sender.send_message = AsyncMock(return_value={"ok": True})

    await receiver.handle_message("user42", "hi there", {"foo": "bar"})

    # Expect send_message to be called twice (two bot messages)
    assert receiver.sender.send_message.call_count == 2


# End of tests