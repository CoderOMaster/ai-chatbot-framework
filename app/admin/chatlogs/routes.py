from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter(prefix="/chatlogs", tags=["chatlogs"]) 


class ChatlogsRepository:
    """Repository interface for chatlog read operations.

    Implementations should provide async methods used by the HTTP handlers so
    the transport layer (FastAPI / Lambda) can be separated from storage.
    """

    async def list_chatlogs(
        self,
        page: int,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> Any:
        raise NotImplementedError

    async def get_chat_thread(self, thread_id: str) -> Optional[Any]:
        raise NotImplementedError


class DefaultChatlogsRepository(ChatlogsRepository):
    """Default repository implementation that delegates to the legacy store
    module. The store module is imported lazily to avoid hard module-level
    coupling and to keep this file suitable for dependency injection.
    """

    def __init__(self, collection: Optional[Any] = None) -> None:
        self._collection = collection

    async def list_chatlogs(
        self,
        page: int,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> Any:
        # Import lazily so callers can inject alternate repository
        import app.admin.chatlogs.store as store

        return await store.list_chatlogs(page=page, limit=limit, start_date=start_date, end_date=end_date, collection=self._collection)

    async def get_chat_thread(self, thread_id: str) -> Optional[Any]:
        import app.admin.chatlogs.store as store

        return await store.get_chat_thread(thread_id, collection=self._collection)


async def get_chatlogs_repository() -> ChatlogsRepository:
    """Dependency provider returning the default repository.

    Tests or alternative services may override this dependency to swap in a
    different backend implementation.
    """

    return DefaultChatlogsRepository()


@router.get("/")
async def list_chatlogs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    repo: ChatlogsRepository = Depends(get_chatlogs_repository),
):
    """Get paginated chat conversation history with optional date filtering.

    Validates query parameters and delegates the read to an injected
    ChatlogsRepository. Returns 400 on invalid date ranges.
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_date cannot be after end_date")

    return await repo.list_chatlogs(page=page, limit=limit, start_date=start_date, end_date=end_date)


@router.get("/{thread_id}")
async def get_chat_thread(thread_id: str, repo: ChatlogsRepository = Depends(get_chatlogs_repository)):
    """Get complete conversation history for a specific thread.

    Returns 404 when the thread is not found.
    """
    conversation = await repo.get_chat_thread(thread_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return conversation