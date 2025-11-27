from typing import Optional, Any
from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from starlette.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorCollection

import app.admin.chatlogs.store as store

router = APIRouter(prefix="/chatlogs", tags=["chatlogs"])


def get_store() -> Any:
    """Dependency that returns the chatlogs store module.

    This allows swapping the store implementation for testing or different
    deployment environments.
    """
    return store


async def get_chatlogs_collection(request: Request) -> AsyncIOMotorCollection:
    """Resolve and return the AsyncIOMotorCollection for chatlogs from app state.

    The function looks for common attributes placed on app.state by application
    startup (e.g. `db` or `mongodb`) and then attempts to locate a
    `chatlogs` collection. If the collection cannot be found a 500 HTTP error
    is raised so callers get a clear failure instead of a server crash.
    """
    db = getattr(request.app.state, "db", None) or getattr(request.app.state, "mongodb", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database not configured")

    # Support different app.state shapes (motor DB, attribute access, dict)
    if hasattr(db, "get_collection"):
        collection = db.get_collection("chatlogs")
    elif hasattr(db, "chatlogs"):
        collection = getattr(db, "chatlogs")
    elif isinstance(db, dict) and "chatlogs" in db:
        collection = db["chatlogs"]
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Chatlogs collection not found in app state")

    return collection


@router.get("/")
async def list_chatlogs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    collection: AsyncIOMotorCollection = Depends(get_chatlogs_collection),
    store_module: Any = Depends(get_store),
):
    """Get chat thread summaries with cursor-based pagination and optional date filtering.

    - limit is bounded (1..100) to avoid very large responses
    - page remains supported for backward compatibility (skip-based paging)
    - cursor is a stringified ObjectId used for efficient paging
    - start_date and end_date must be a valid ISO datetime; FastAPI will
      reject invalid formats. We additionally ensure start_date <= end_date.
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_date must be <= end_date")

    response = await store_module.list_chatlogs(collection, page=page, limit=limit, cursor=cursor, start_date=start_date, end_date=end_date)
    return response


@router.get("/{thread_id}")
async def get_chat_thread(
    thread_id: str,
    collection: AsyncIOMotorCollection = Depends(get_chatlogs_collection),
    store_module: Any = Depends(get_store),
):
    """Stream the full conversation for a thread as a JSON array.

    Returns a 404 HTTPException when the thread is not found. The response is
    streamed to avoid materializing large conversations in memory.
    """
    messages = await store_module.get_chat_thread(collection, thread_id)
    if not messages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    async def _stream() -> "AsyncGenerator[bytes, None]":
        # Stream a JSON array of objects. Each message is expected to be a
        # Pydantic model or dict-like object; fall back to string conversion.
        first = True
        yield b"["
        for msg in messages:
            if not first:
                yield b","
            else:
                first = False

            try:
                # Prefer Pydantic .dict() if available to avoid leaking internal state
                obj = msg.dict() if hasattr(msg, "dict") else dict(msg)
            except Exception:
                obj = {"value": str(msg)}

            yield json.dumps(obj, default=str).encode("utf-8")
        yield b"]"

    return StreamingResponse(_stream(), media_type="application/json")