from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from app.admin.chatlogs.routes import (
    ChatlogsRepository,
    StoreChatlogsRepository,
    _validate_date_filter_order,
    get_chatlogs_repository,
    router,
)
from app.admin.chatlogs.schemas import (
    BotMessage,
    ChatLog,
    ChatLogResponse,
    ChatMessage,
)


def _build_test_app(repository: ChatlogsRepository) -> FastAPI:
    """Return a FastAPI application wired to the provided repository implementation."""

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chatlogs_repository] = lambda: repository
    return app


def test_validate_date_filter_order_allows_equal_or_missing_dates() -> None:
    """Ensure the helper accepts ranges that describe a valid period."""

    _validate_date_filter_order(datetime(2024, 1, 1), datetime(2024, 1, 1))
    _validate_date_filter_order(datetime(2024, 1, 1), None)
    _validate_date_filter_order(None, datetime(2024, 1, 1))


def test_validate_date_filter_order_raises_for_backwards_ranges() -> None:
    """Ensure the helper rejects ranges where the start comes after the end."""

    with pytest.raises(HTTPException) as excinfo:
        _validate_date_filter_order(datetime(2024, 1, 5), datetime(2024, 1, 1))

    assert "start_date cannot be later than end_date" in str(excinfo.value)


@pytest.mark.asyncio
async def test_list_chatlogs_success_returns_repository_payload() -> None:
    """Verify the list endpoint defers to the repository and emits its response."""

    repository = AsyncMock(spec=ChatlogsRepository)
    sample_response = ChatLogResponse(
        total=2,
        page=2,
        limit=5,
        conversations=[
            {"thread_id": "some-thread", "date": datetime(2024, 1, 1, 12, 0, 0)}
        ],
    )
    repository.list_chatlogs = AsyncMock(return_value=sample_response)

    app = _build_test_app(repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/chatlogs/",
            params={
                "page": 2,
                "limit": 5,
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-01-31T00:00:00",
            },
        )

    assert response.status_code == 200
    assert response.json() == sample_response.model_dump(mode='json')
    repository.list_chatlogs.assert_awaited_once_with(
        2,
        5,
        datetime.fromisoformat("2024-01-01T00:00:00"),
        datetime.fromisoformat("2024-01-31T00:00:00"),
    )


@pytest.mark.asyncio
async def test_list_chatlogs_invalid_date_range_returns_400() -> None:
    """Ensure the list endpoint rejects invalid date ranges before calling the repository."""

    repository = AsyncMock(spec=ChatlogsRepository)
    repository.list_chatlogs = AsyncMock()

    app = _build_test_app(repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/chatlogs/",
            params={
                "start_date": "2024-01-10T00:00:00",
                "end_date": "2024-01-01T00:00:00",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "start_date cannot be later than end_date"
    repository.list_chatlogs.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_chat_thread_returns_conversation_when_found() -> None:
    """Confirm that the thread endpoint returns stored messages when the thread exists."""

    repository = AsyncMock(spec=ChatlogsRepository)
    conversation = ChatLog(
        user_message=ChatMessage(text="hi"),
        bot_message=[BotMessage(text="hello")],
        date=datetime(2024, 1, 2, 10, 0, 0),
    )
    repository.get_chat_thread = AsyncMock(return_value=[conversation])

    app = _build_test_app(repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/chatlogs/thread-abc")

    assert response.status_code == 200
    assert response.json() == [conversation.model_dump(mode='json')]
    repository.get_chat_thread.assert_awaited_once_with("thread-abc")


@pytest.mark.asyncio
async def test_get_chat_thread_missing_returns_404() -> None:
    """Ensure missing threads are translated into HTTP 404 errors."""

    repository = AsyncMock(spec=ChatlogsRepository)
    repository.get_chat_thread = AsyncMock(return_value=None)

    app = _build_test_app(repository)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/chatlogs/thread-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"
    repository.get_chat_thread.assert_awaited_once_with("thread-missing")


@pytest.mark.asyncio
async def test_store_repository_list_chatlogs_delegates_to_store(monkeypatch) -> None:
    """Verify StoreChatlogsRepository proxies list requests to the underlying store implementation."""

    sample_response = ChatLogResponse(
        total=1,
        page=1,
        limit=10,
        conversations=[
            {"thread_id": "thread-store", "date": datetime(2024, 2, 1, 0, 0, 0)}
        ],
    )

    store_list = AsyncMock(return_value=sample_response)
    monkeypatch.setattr(
        "app.admin.chatlogs.routes.list_chatlogs_from_store",
        store_list,
    )

    repository = StoreChatlogsRepository()
    end_date = datetime(2024, 2, 2, 0, 0, 0)
    result = await repository.list_chatlogs(1, 10, None, end_date)

    assert result is sample_response
    store_list.assert_awaited_once_with(
        page=1,
        limit=10,
        start_date=None,
        end_date=end_date,
    )


@pytest.mark.asyncio
async def test_store_repository_get_chat_thread_delegates_to_store(monkeypatch) -> None:
    """Verify StoreChatlogsRepository proxies single thread lookups to the store implementation."""

    sample_conversation = [
        ChatLog(
            user_message=ChatMessage(text="hi there"),
            bot_message=[BotMessage(text="hello")],
            date=datetime(2024, 3, 3, 3, 3, 3),
        )
    ]

    store_get = AsyncMock(return_value=sample_conversation)
    monkeypatch.setattr(
        "app.admin.chatlogs.routes.get_chat_thread_from_store",
        store_get,
    )

    repository = StoreChatlogsRepository()
    result = await repository.get_chat_thread("thread-x")

    assert result is sample_conversation
    store_get.assert_awaited_once_with("thread-x")