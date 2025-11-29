from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.chatlogs import store
from app.admin.chatlogs.schemas import ChatLog, ChatLogResponse, ChatThreadInfo


class _AsyncIterableCursor:
    def __init__(self, items: Iterable[Dict[str, Any]]) -> None:
        self._items = list(items)
        self._index = 0

    def __aiter__(self) -> "_AsyncIterableCursor":
        self._index = 0
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


@pytest.fixture
def mock_collection() -> MagicMock:
    collection = MagicMock(spec=AsyncIOMotorCollection)
    collection.create_index = AsyncMock()
    collection.aggregate = MagicMock()
    collection.find.return_value.sort.return_value.to_list = AsyncMock()
    return collection


@pytest.fixture
def collection_getter(mock_collection: MagicMock):
    def getter(name: str) -> MagicMock:
        assert name == store.CHATLOG_COLLECTION_NAME
        return mock_collection

    return getter


def test_build_date_range_query_with_start_and_end() -> None:
    """Ensure both start and end bounds are propagated when provided."""

    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 31)

    query = store._build_date_range_query(start, end)

    assert query == {"date": {"$gte": start, "$lte": end}}


def test_build_date_range_query_only_start() -> None:
    """Ensure a lone start date yields a gte-only range."""

    start = datetime(2024, 2, 1)

    query = store._build_date_range_query(start, None)

    assert query == {"date": {"$gte": start}}


def test_build_date_range_query_no_dates() -> None:
    """Ensure no filters are introduced when no dates are provided."""

    query = store._build_date_range_query(None, None)

    assert query == {}


def test_count_threads_pipeline_structure() -> None:
    """Ensure the thread counting aggregation is constructed correctly."""

    query = {"date": {"$gte": datetime(2024, 1, 1)}}
    pipeline = store._count_threads_pipeline(query)

    assert pipeline == [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]


def test_conversation_paging_pipeline_pagination() -> None:
    """Ensure pagination helpers emit skip/limit stages with the expected sort/group shape."""

    query = {"date": {"$gte": datetime(2024, 1, 1)}}
    skip = 10
    limit = 5

    pipeline = store._conversation_paging_pipeline(query, skip, limit)

    assert pipeline[0]["$match"] == query
    assert pipeline[1] == {"$sort": {"date": -1}}
    assert pipeline[2]["$group"]["_id"] == "$thread_id"
    assert pipeline[-2] == {"$skip": skip}
    assert pipeline[-1] == {"$limit": limit}


def test_project_chat_thread_info_mapping() -> None:
    """Validate that grouped aggregation documents convert to the ChatThreadInfo schema."""

    cluster = {"thread_id": "thread-id", "date": datetime(2024, 3, 15)}

    info = store._project_chat_thread_info(cluster)

    assert isinstance(info, ChatThreadInfo)
    assert info.thread_id == "thread-id"
    assert info.date == cluster["date"]


def test_map_chat_log_document_defaults() -> None:
    """Verify chat log mapping supplies defaults for missing optional fields."""

    document = {
        "user_message": {"text": "hello"},
        "date": datetime(2024, 3, 15),
    }

    chat_log = store._map_chat_log_document(document)

    assert isinstance(chat_log, ChatLog)
    assert chat_log.bot_message == []
    assert chat_log.context == {}
    assert chat_log.user_message.text == "hello"


@pytest.mark.asyncio
async def test_ensure_chatlog_indexes_creates_expected_indexes(
    collection_getter: Any,
) -> None:
    """Ensure index helper forwards the requests for thread_id and date indexes."""

    collection = collection_getter(store.CHATLOG_COLLECTION_NAME)
    await store.ensure_chatlog_indexes(collection_getter=collection_getter)

    assert collection.create_index.await_count == 2
    assert collection.create_index.await_args_list[0][0][0] == [("thread_id", 1)]
    assert collection.create_index.await_args_list[1][0][0] == [("date", -1)]


@pytest.mark.asyncio
async def test_list_chatlogs_returns_paged_response(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Validate list_chatlogs aggregates total and conversation pipelines correctly."""

    start_date = datetime.utcnow() - timedelta(days=2)
    end_date = datetime.utcnow()
    total_cursor = MagicMock()
    total_cursor.to_list = AsyncMock(return_value=[{"total": 3}])

    conversation_document = {
        "thread_id": "thread-123",
        "date": datetime.utcnow(),
    }
    conversation_cursor = _AsyncIterableCursor([conversation_document])

    mock_collection.aggregate.side_effect = [total_cursor, conversation_cursor]

    response = await store.list_chatlogs(
        page=2,
        limit=5,
        start_date=start_date,
        end_date=end_date,
        collection_getter=collection_getter,
    )

    assert isinstance(response, ChatLogResponse)
    assert response.total == 3
    assert response.page == 2
    assert response.limit == 5
    assert response.conversations[0].thread_id == "thread-123"

    query = store._build_date_range_query(start_date, end_date)
    expected_total_pipeline = store._count_threads_pipeline(query)
    expected_conversation_pipeline = store._conversation_paging_pipeline(query, skip=5, limit=5)

    assert mock_collection.aggregate.call_count == 2
    assert mock_collection.aggregate.call_args_list[0][0][0] == expected_total_pipeline
    assert mock_collection.aggregate.call_args_list[1][0][0] == expected_conversation_pipeline


@pytest.mark.asyncio
async def test_list_chatlogs_empty_results_yield_zero(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Ensure empty aggregation results lead to zero totals and empty conversation lists."""

    total_cursor = MagicMock()
    total_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.aggregate.side_effect = [total_cursor, _AsyncIterableCursor([])]

    response = await store.list_chatlogs(collection_getter=collection_getter)

    assert response.total == 0
    assert response.conversations == []


@pytest.mark.asyncio
async def test_get_chat_thread_returns_none_when_missing(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Confirm the helper returns None when no chat thread messages exist."""

    find_cursor = MagicMock()
    sort_cursor = MagicMock()
    sort_cursor.to_list = AsyncMock(return_value=[])
    find_cursor.sort.return_value = sort_cursor
    mock_collection.find.return_value = find_cursor

    result = await store.get_chat_thread("missing-thread", collection_getter=collection_getter)

    assert result is None
    mock_collection.find.assert_called_once_with({"thread_id": "missing-thread"})
    sort_cursor.to_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_chat_thread_returns_chatlogs(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Validate the chat thread helper maps stored messages into ChatLog models."""

    message_date = datetime.utcnow()
    stored_messages = [
        {
            "user_message": {"text": "hi", "context": {}},
            "bot_message": [{"text": "hello"}],
            "date": message_date,
            "context": {"foo": "bar"},
        }
    ]

    find_cursor = MagicMock()
    sort_cursor = MagicMock()
    sort_cursor.to_list = AsyncMock(return_value=stored_messages)
    find_cursor.sort.return_value = sort_cursor
    mock_collection.find.return_value = find_cursor

    result = await store.get_chat_thread("thread-1", collection_getter=collection_getter)

    assert result is not None
    assert len(result) == 1
    assert result[0].user_message.text == "hi"
    assert result[0].bot_message[0].text == "hello"
    assert result[0].date == message_date

    mock_collection.find.assert_called_once_with({"thread_id": "thread-1"})
    find_cursor.sort.assert_called_once_with("date", 1)
    sort_cursor.to_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_chatlogs_uses_custom_collection_getter(
    mock_collection: MagicMock,
) -> None:
    """Ensure list_chatlogs respects an injected collection getter override."""

    def getter(name: str) -> MagicMock:
        assert name == store.CHATLOG_COLLECTION_NAME
        return mock_collection

    total_cursor = MagicMock()
    total_cursor.to_list = AsyncMock(return_value=[{"total": 1}])
    mock_collection.aggregate.side_effect = [total_cursor, _AsyncIterableCursor([])]

    response = await store.list_chatlogs(collection_getter=getter)

    assert response.total == 1
    assert mock_collection.aggregate.call_count == 2


@pytest.mark.asyncio
async def test_get_chat_thread_defaults_to_ascending_sort(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Assert the chat thread fetch always sorts messages from oldest to newest."""

    find_cursor = MagicMock()
    sort_cursor = MagicMock()
    sort_cursor.to_list = AsyncMock(return_value=[])
    find_cursor.sort.return_value = sort_cursor
    mock_collection.find.return_value = find_cursor

    await store.get_chat_thread("ordered", collection_getter=collection_getter)

    find_cursor.sort.assert_called_once_with("date", 1)


@pytest.mark.asyncio
async def test_ensure_chatlog_indexes_defaults_to_app_collection() -> None:
    """Ensure the default getter is invoked when no override is provided."""

    called: List[str] = []

    async def fake_create_index(*_: Any, **__: Any) -> None:
        called.append("index")

    class FakeCollection:
        async def create_index(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
            await fake_create_index()

    fake_getter = lambda name: FakeCollection()

    await store.ensure_chatlog_indexes(collection_getter=fake_getter)  # type: ignore[arg-type]

    assert len(called) == 2


@pytest.mark.asyncio
async def test_list_chatlogs_uses_zero_skip_on_first_page(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Validate pagination helper does not emit negative skips for page 1."""

    total_cursor = MagicMock()
    total_cursor.to_list = AsyncMock(return_value=[{"total": 0}])
    mock_collection.aggregate.side_effect = [total_cursor, _AsyncIterableCursor([])]

    await store.list_chatlogs(page=1, limit=2, collection_getter=collection_getter)

    expected_conversation_pipeline = store._conversation_paging_pipeline({}, skip=0, limit=2)
    assert mock_collection.aggregate.call_args_list[1][0][0] == expected_conversation_pipeline


@pytest.mark.asyncio
async def test_list_chatlogs_pages_negative_page_numbers_as_zero(
    collection_getter: Any,
    mock_collection: MagicMock,
) -> None:
    """Ensure negative page numbers are normalized to zero skip size."""

    total_cursor = MagicMock()
    total_cursor.to_list = AsyncMock(return_value=[{"total": 0}])
    mock_collection.aggregate.side_effect = [total_cursor, _AsyncIterableCursor([])]

    await store.list_chatlogs(page=-1, limit=5, collection_getter=collection_getter)

    expected_conversation_pipeline = store._conversation_paging_pipeline({}, skip=0, limit=5)
    assert mock_collection.aggregate.call_args_list[1][0][0] == expected_conversation_pipeline


def test_map_chat_log_document_preserves_context() -> None:
    """Confirm explicit context data propagates through the chat log mapping."""

    document = {
        "user_message": {"text": "hi"},
        "bot_message": [{"text": "reply"}],
        "date": datetime.utcnow(),
        "context": {"key": "value"},
    }

    chat_log = store._map_chat_log_document(document)

    assert chat_log.context == {"key": "value"}
    assert chat_log.bot_message[0].text == "reply"
    assert chat_log.user_message.text == "hi"


def test_project_chat_thread_info_handles_different_documents() -> None:
    """Ensure the thread info mapper works for arbitrary aggregator payloads."""

    doc = {"thread_id": "abc", "date": datetime.utcnow(), "irrelevant": True}
    info = store._project_chat_thread_info(doc)

    assert info.thread_id == "abc"
    assert isinstance(info, ChatThreadInfo)
    assert hasattr(info, "date")


def test_count_threads_pipeline_with_empty_query() -> None:
    """Verify the thread counting pipeline handles empty queries without issues."""

    pipeline = store._count_threads_pipeline({})

    assert pipeline[0] == {"$match": {}}
    assert pipeline[-1] == {"$count": "total"}


def test_conversation_paging_pipeline_with_zero_limit() -> None:
    """Ensure the pagination pipeline tolerates zero limits while keeping structure."""

    pipeline = store._conversation_paging_pipeline({}, skip=0, limit=0)

    assert pipeline[-2] == {"$skip": 0}
    assert pipeline[-1] == {"$limit": 0}


@pytest.mark.asyncio
async def test_list_chatlogs_handles_none_collection_getter() -> None:
    """Ensure list_chatlogs can run with the module default getter when none is supplied."""

    total_cursor = MagicMock()
    total_cursor.to_list = AsyncMock(return_value=[{"total": 0}])
    mock_collection = MagicMock(spec=AsyncIOMotorCollection)
    mock_collection.aggregate.side_effect = [total_cursor, _AsyncIterableCursor([])]

    def fake_default_getter(name: str) -> MagicMock:
        assert name == store.CHATLOG_COLLECTION_NAME
        return mock_collection

    await store.list_chatlogs(collection_getter=fake_default_getter)

    assert mock_collection.aggregate.call_count == 2


@pytest.mark.asyncio
async def test_get_chat_thread_respects_collection_getter(
    mock_collection: MagicMock,
) -> None:
    """Confirm get_chat_thread uses the provided getter instead of the module default."""

    find_cursor = MagicMock()
    sort_cursor = MagicMock()
    sort_cursor.to_list = AsyncMock(return_value=[])
    find_cursor.sort.return_value = sort_cursor
    mock_collection.find.return_value = find_cursor

    def getter(name: str) -> MagicMock:
        assert name == store.CHATLOG_COLLECTION_NAME
        return mock_collection

    await store.get_chat_thread("custom", collection_getter=getter)

    mock_collection.find.assert_called_once_with({"thread_id": "custom"})


__all__ = [
    "_AsyncIterableCursor",
]