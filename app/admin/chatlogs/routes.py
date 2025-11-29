from datetime import datetime
from typing import Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query

from app.admin.chatlogs.schemas import ChatLog, ChatLogResponse
from app.admin.chatlogs.store import (
    get_chat_thread as get_chat_thread_from_store,
    list_chatlogs as list_chatlogs_from_store,
)


router = APIRouter(prefix="/chatlogs", tags=["chatlogs"])


class ChatlogsRepository(Protocol):
    """Contract describing chatlog read operations."""

    async def list_chatlogs(
        self,
        page: int,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> ChatLogResponse:
        """Return a paginated list of chat threads matching the provided filters."""

    async def get_chat_thread(self, thread_id: str) -> Optional[list[ChatLog]]:
        """Return the messages for a chat thread, emitting None when it does not exist."""


class StoreChatlogsRepository(ChatlogsRepository):
    """Default repository that proxies to the existing chatlog store helpers."""

    async def list_chatlogs(
        self,
        page: int,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> ChatLogResponse:
        return await list_chatlogs_from_store(
            page=page,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_chat_thread(self, thread_id: str) -> Optional[list[ChatLog]]:
        return await get_chat_thread_from_store(thread_id)


_chatlogs_repository: ChatlogsRepository = StoreChatlogsRepository()


def get_chatlogs_repository() -> ChatlogsRepository:
    """Provide the default chatlogs repository implementation."""

    return _chatlogs_repository


def _validate_date_filter_order(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> None:
    """Ensure the provided start and end dates describe a valid range."""

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date",
        )


@router.get("/", response_model=ChatLogResponse)
async def list_chatlogs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    repository: ChatlogsRepository = Depends(get_chatlogs_repository),
) -> ChatLogResponse:
    """Return paginated chat history optionally scoped to a date range."""

    _validate_date_filter_order(start_date, end_date)
    return await repository.list_chatlogs(page, limit, start_date, end_date)


@router.get("/{thread_id}", response_model=list[ChatLog])
async def get_chat_thread(
    thread_id: str,
    repository: ChatlogsRepository = Depends(get_chatlogs_repository),
) -> list[ChatLog]:
    """Return every message recorded in a specific chat thread."""

    conversation = await repository.get_chat_thread(thread_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation


__all__ = [
    "ChatlogsRepository",
    "get_chatlogs_repository",
]