import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId

import app.admin.chatlogs.store as store


class AsyncCursor:
    """Simple async cursor to emulate Motor cursor/aggregate results."""
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *args, **kwargs):
        return self

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for d in self._docs:
            yield d

    async def to_list(self, length=None):
        return self._docs


@pytest.fixture(autouse=True)
def patch_collections(monkeypatch):
    """Patch the module-level collection and archive_collection with mocks for each test."""
    mock_collection = MagicMock()
    mock_archive = MagicMock()

    # Async methods
    mock_collection.create_index = AsyncMock()
    mock_collection.find = AsyncMock()
    mock_collection.aggregate = AsyncMock()
    mock_collection.delete_many = AsyncMock()

    mock_archive.insert_many = AsyncMock()

    monkeypatch.setattr(store, "collection", mock_collection)
    monkeypatch.setattr(store, "archive_collection", mock_archive)

    return mock_collection, mock_archive


@pytest.mark.asyncio
async def test_setup_indexes_calls_create_index(patch_collections):
    """Ensure setup_indexes creates TTL, compound, text and date indexes."""
    mock_collection, _ = patch_collections

    await store.setup_indexes()

    # Expect create_index to be called at least 4 times
    assert mock_collection.create_index.await_count >= 4

    # Check first call contains TTL on 'date'
    first_call_args = mock_collection.create_index.await_args_list[0].args
    assert "date" in first_call_args


@pytest.mark.asyncio
async def test_archive_old_logs_no_documents(patch_collections):
    """When there are no old documents archive_old_logs should return 0 and not call insert_many."""
    mock_collection, mock_archive = patch_collections

    # find returns empty list
    mock_collection.find.return_value = AsyncCursor([])
    mock_collection.delete_many.return_value = MagicMock(deleted_count=0)

    count = await store.archive_old_logs(days_threshold=1)
    assert count == 0
    mock_archive.insert_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_old_logs_with_documents(patch_collections):
    """Archive moves documents to archive collection and deletes them from active collection."""
    mock_collection, mock_archive = patch_collections

    docs = [{"_id": ObjectId(), "date": datetime.utcnow() - timedelta(days=10)}, {"_id": ObjectId(), "date": datetime.utcnow() - timedelta(days=20)}]
    mock_collection.find.return_value = AsyncCursor(docs)
    mock_archive.insert_many = AsyncMock()
    mock_collection.delete_many.return_value = MagicMock(deleted_count=2)

    result = await store.archive_old_logs(days_threshold=1)
    assert result == 2
    mock_archive.insert_many.assert_awaited_once_with(docs)
    mock_collection.delete_many.assert_awaited_once()


def test_anonymize_message_replaces_email_and_phone():
    """_anonymize_message should replace email addresses and phone numbers with anonymized tokens."""
    sample = "Contact me at john.doe@example.com or 123-456-7890"
    anonymized = store._anonymize_message(sample, hash_length=6)
    assert "[ANON_" in anonymized
    assert "example.com" not in anonymized
    assert "123-456-7890" not in anonymized


@pytest.mark.asyncio
async def test_list_chatlogs_with_cursor_and_search(monkeypatch, patch_collections):
    """list_chatlogs should return a ChatLogResponse with conversations and next_cursor when docs exist. It should handle an invalid cursor gracefully."""
    mock_collection, _ = patch_collections

    # Prepare count pipeline response
    def aggregate_side_effect(pipeline):
        # detect count pipeline by presence of {'$count': 'total'}
        if any(isinstance(p, dict) and p.get("$count") for p in pipeline):
            return AsyncCursor([{"total": 2}])
        return AsyncCursor([
            {"thread_id": "t1", "date": datetime.utcnow(), "last_id": ObjectId()},
            {"thread_id": "t2", "date": datetime.utcnow(), "last_id": ObjectId()},
        ])

    mock_collection.aggregate.side_effect = aggregate_side_effect

    # Call with invalid cursor (should be ignored)
    response = await store.list_chatlogs(page=1, limit=2, cursor="invalidcursor", search_query="hello")

    assert response.total == 2
    assert response.page == 1
    assert response.limit == 2
    assert len(response.conversations) == 2
    # next_cursor should be set (string of ObjectId)
    assert hasattr(response, "next_cursor")


@pytest.mark.asyncio
async def test_get_chat_thread_various_bot_message_formats(patch_collections):
    """get_chat_thread should normalize bot_message into list of dicts and optionally anonymize messages."""
    mock_collection, _ = patch_collections

    docs = [
        {"thread_id": "t1", "date": datetime(2020, 1, 1), "user_message": {"text": "hello user@test.com"}, "bot_message": "hi"},
        {"thread_id": "t1", "date": datetime(2020, 1, 2), "user_message": {"text": "call 123-456-7890"}, "bot_message": [{"text": "response"}]},
        {"thread_id": "t1", "date": datetime(2020, 1, 3), "user_message": "plain string user message", "bot_message": 12345},
    ]

    # collection.find(...).sort(...).to_list(...) chain
    mock_collection.find.return_value = AsyncCursor(docs)

    # Without anonymize
    result = await store.get_chat_thread("t1", anonymize=False)
    assert isinstance(result, list)
    assert result[0].bot_message[0].text == "hi"

    # With anonymize - emails and phone numbers should be anonymized
    result_anon = await store.get_chat_thread("t1", anonymize=True)
    assert "[ANON_" in result_anon[0].user_message.text
    assert "123-456-7890" not in result_anon[1].user_message.text


@pytest.mark.asyncio
async def test_search_chatlogs_returns_results(patch_collections):
    """search_chatlogs should return aggregate to_list results based on full-text search pipeline."""
    mock_collection, _ = patch_collections

    docs = [{"_id": ObjectId(), "score": 5, "user_message": {"text": "hello"}}]
    mock_collection.aggregate.return_value = AsyncCursor(docs)

    results = await store.search_chatlogs("hello", limit=10, skip=0)
    assert results == docs


@pytest.mark.asyncio
async def test_get_thread_statistics_empty_and_nonempty(patch_collections):
    """get_thread_statistics should return {} when no aggregation result and the dict when exists."""
    mock_collection, _ = patch_collections

    # Empty case
    mock_collection.aggregate.return_value = AsyncCursor([])
    stats = await store.get_thread_statistics("no-thread")
    assert stats == {}

    # Non-empty case
    expected = [{"_id": "t1", "message_count": 3, "first_message": datetime.utcnow(), "last_message": datetime.utcnow(), "avg_context_size": 10}]
    mock_collection.aggregate.return_value = AsyncCursor(expected)
    stats2 = await store.get_thread_statistics("t1")
    assert stats2.get("_id") == "t1"


@pytest.mark.asyncio
async def test_delete_thread_returns_deleted_count(patch_collections):
    """delete_thread should return number of deleted documents as reported by delete_many."""
    mock_collection, _ = patch_collections
    mock_collection.delete_many.return_value = MagicMock(deleted_count=4)

    deleted = await store.delete_thread("thread-x")
    assert deleted == 4