import asyncio
from datetime import datetime, timedelta
import hashlib
import json

import pytest
import httpx

from app.admin.test import routes
from pydantic import ValidationError
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def clear_state():
    """Clear in-memory cache and history before each test."""
    routes._test_cache.clear()
    routes._test_history.clear()
    yield
    routes._test_cache.clear()
    routes._test_history.clear()


def test_messageformat_valid():
    """MessageFormat accepts valid thread_id and text."""
    msg = routes.MessageFormat(thread_id="thread-1", text="Hello", context={"a": 1})
    assert msg.thread_id == "thread-1"
    assert msg.text == "Hello"
    assert msg.context == {"a": 1}


def test_messageformat_invalid_thread_id():
    """MessageFormat rejects invalid thread_id characters."""
    with pytest.raises(ValidationError):
        routes.MessageFormat(thread_id="bad id!", text="Hi")


def test_messageformat_text_whitespace():
    """MessageFormat rejects text that is only whitespace."""
    with pytest.raises(ValidationError):
        routes.MessageFormat(thread_id="t1", text="   \n  ")


def test_generate_message_hash_consistency():
    """_generate_message_hash produces same hash for same content and independent of context key order."""
    m1 = routes.MessageFormat(thread_id="t1", text="hello", context={"b": 2, "a": 1})
    m2 = routes.MessageFormat(thread_id="t1", text="hello", context={"a": 1, "b": 2})
    h1 = routes._generate_message_hash(m1)
    h2 = routes._generate_message_hash(m2)
    assert h1 == h2


def test_validate_auth_token_missing():
    """_validate_auth_token raises when header missing."""
    with pytest.raises(HTTPException) as exc:
        routes._validate_auth_token(None)
    assert exc.value.status_code == 401


def test_validate_auth_token_format_and_length():
    """_validate_auth_token raises for wrong format or short token, accepts valid token."""
    with pytest.raises(HTTPException):
        routes._validate_auth_token("NotBearer token")
    with pytest.raises(HTTPException):
        routes._validate_auth_token("Bearer short")
    # valid
    token = routes._validate_auth_token("Bearer validtoken123")
    assert token == "validtoken123"


def test_cache_and_get_cached_result_hit_and_expire():
    """_cache_result stores and _get_cached_result returns until TTL expires."""
    msg = routes.MessageFormat(thread_id="t1", text="hi")
    h = routes._generate_message_hash(msg)
    result = routes.TestResult(
        message_id=h, thread_id="t1", input_text="hi", output={"r": 1}, timestamp=datetime.utcnow()
    )
    # insert with current time -> hit
    routes._cache_result(h, result)
    cached = routes._get_cached_result(h)
    assert cached is not None
    assert cached.message_id == h

    # simulate expiry by setting timestamp in the past
    routes._test_cache[h] = (result, datetime.utcnow() - timedelta(seconds=routes.CACHE_TTL_SECONDS + 10))
    expired = routes._get_cached_result(h)
    assert expired is None


class MockResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class MockClientSuccess:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        return MockResponse(status_code=200, json_data={"reply": "ok", "received": json})


class MockClientErrorStatus(MockClientSuccess):
    async def post(self, url, json=None, headers=None):
        return MockResponse(status_code=500, text="server error")


class MockClientTimeout:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        raise httpx.TimeoutException("timeout")


@pytest.mark.asyncio
async def test_call_dialogue_manager_service_success(monkeypatch):
    """_call_dialogue_manager_service returns JSON on 200 response."""
    monkeypatch.setattr(routes.httpx, "AsyncClient", MockClientSuccess)
    msg = routes.MessageFormat(thread_id="t1", text="hey", context={"k": "v"})
    res = await routes._call_dialogue_manager_service(msg)
    assert res["reply"] == "ok"
    assert res["received"]["text"] == "hey"


@pytest.mark.asyncio
async def test_call_dialogue_manager_service_non200(monkeypatch):
    """_call_dialogue_manager_service raises HTTPException on non-200 status."""
    monkeypatch.setattr(routes.httpx, "AsyncClient", MockClientErrorStatus)
    msg = routes.MessageFormat(thread_id="t1", text="hey")
    with pytest.raises(HTTPException) as exc:
        await routes._call_dialogue_manager_service(msg)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_call_dialogue_manager_service_timeout(monkeypatch):
    """_call_dialogue_manager_service maps timeouts to 504 HTTPException."""
    monkeypatch.setattr(routes.httpx, "AsyncClient", MockClientTimeout)
    msg = routes.MessageFormat(thread_id="t1", text="hey")
    with pytest.raises(HTTPException) as exc:
        await routes._call_dialogue_manager_service(msg)
    assert exc.value.status_code == 504


@pytest.mark.asyncio
async def test_chat_cached_hit(monkeypatch):
    """chat returns cached result and marks cache_hit True when cached."""
    msg = routes.MessageFormat(thread_id="t1", text="hi")
    h = routes._generate_message_hash(msg)
    result = routes.TestResult(message_id=h, thread_id="t1", input_text="hi", output={"r": 1}, timestamp=datetime.utcnow())
    routes._test_cache[h] = (result, datetime.utcnow())

    resp = await routes.chat(msg, authorization="Bearer token12345")
    assert resp["message_id"] == h
    assert resp["cache_hit"] is True


@pytest.mark.asyncio
async def test_chat_calls_service_and_caches(monkeypatch):
    """chat calls dialogue-manager on cache miss, returns result and caches it."""
    monkeypatch.setattr(routes.httpx, "AsyncClient", MockClientSuccess)
    msg = routes.MessageFormat(thread_id="t1", text="hello")
    resp = await routes.chat(msg, authorization="Bearer validtoken123")
    assert resp["input_text"] == "hello"
    assert resp["cache_hit"] is False
    # ensure cached
    h = routes._generate_message_hash(msg)
    cached = routes._get_cached_result(h)
    assert cached is not None


@pytest.mark.asyncio
async def test_chat_auth_fail():
    """chat raises HTTPException when auth is missing or invalid."""
    msg = routes.MessageFormat(thread_id="t1", text="hi")
    with pytest.raises(HTTPException):
        await routes.chat(msg, authorization=None)


@pytest.mark.asyncio
async def test_test_batch_empty_messages():
    """test_batch rejects an empty message list."""
    with pytest.raises(HTTPException) as exc:
        await routes.test_batch([], authorization="Bearer validtoken123")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_test_batch_too_many_messages():
    """test_batch rejects batches larger than 100 messages."""
    msgs = [routes.MessageFormat(thread_id=f"t{i}", text="hi") for i in range(101)]
    with pytest.raises(HTTPException) as exc:
        await routes.test_batch(msgs, authorization="Bearer validtoken123")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_test_batch_success_and_history(monkeypatch):
    """test_batch processes messages concurrently, caches results, and records history."""
    monkeypatch.setattr(routes.httpx, "AsyncClient", MockClientSuccess)
    msgs = [routes.MessageFormat(thread_id=f"t{i}", text=f"hi{i}") for i in range(3)]
    batch_result = await routes.test_batch(msgs, authorization="Bearer validtoken123")
    assert batch_result.total_messages == 3
    assert batch_result.successful == 3
    assert batch_result.failed == 0
    # check history appended
    assert len(routes._test_history) == 1
    entry = routes._test_history[-1]
    assert entry.results_summary["total"] == 3


@pytest.mark.asyncio
async def test_get_test_history_and_compare(monkeypatch):
    """get_test_history returns last entries and compare_versions computes deltas or raises when not found."""
    # Prepare two history entries
    h1 = routes.TestHistory(batch_id="b1", timestamp=datetime.utcnow(), version="1.0", results_summary={"total": 2, "successful": 1, "failed": 1, "cache_hits": 0, "duration_seconds": 0.5})
    h2 = routes.TestHistory(batch_id="b2", timestamp=datetime.utcnow(), version="1.0", results_summary={"total": 2, "successful": 2, "failed": 0, "cache_hits": 1, "duration_seconds": 0.3})
    routes._test_history.append(h1)
    routes._test_history.append(h2)

    resp = await routes.get_test_history(limit=2, authorization="Bearer validtoken123")
    assert isinstance(resp, list)
    assert len(resp) == 2

    comp = await routes.compare_versions(batch_id_1="b1", batch_id_2="b2", authorization="Bearer validtoken123")
    assert comp["differences"]["successful_delta"] == 1
    assert comp["differences"]["failed_delta"] == -1

    # not found
    with pytest.raises(HTTPException) as exc:
        await routes.compare_versions(batch_id_1="b1", batch_id_2="missing", authorization="Bearer validtoken123")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_cache_stats_auth_and_values():
    """get_cache_stats returns counts and requires auth."""
    # populate cache and history
    msg = routes.MessageFormat(thread_id="t1", text="x")
    h = routes._generate_message_hash(msg)
    routes._cache_result(h, routes.TestResult(message_id=h, thread_id="t1", input_text="x", output={}, timestamp=datetime.utcnow()))
    routes._test_history.append(routes.TestHistory(batch_id="b1", timestamp=datetime.utcnow(), version="1.0", results_summary={}))

    stats = await routes.get_cache_stats(authorization="Bearer validtoken123")
    assert stats["cached_entries"] == 1
    assert stats["history_entries"] == 1

    with pytest.raises(HTTPException):
        await routes.get_cache_stats(authorization=None)