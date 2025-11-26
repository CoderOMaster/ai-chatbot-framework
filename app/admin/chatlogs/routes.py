from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime
import app.admin.chatlogs.store as store

router = APIRouter(prefix="/chatlogs", tags=["chatlogs"])

# Validation constants
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_LIMIT = 10


def validate_pagination(page: int, limit: int) -> tuple[int, int]:
    """
    Validate and normalize pagination parameters.
    
    Args:
        page: Page number (1-indexed)
        limit: Number of results per page
    
    Returns:
        Tuple of (page, limit) with validated values
    
    Raises:
        HTTPException: If validation fails
    """
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}"
        )
    return page, limit


@router.get("/")
async def list_chatlogs(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(DEFAULT_LIMIT, ge=MIN_LIMIT, le=MAX_LIMIT, description="Results per page"),
    start_date: Optional[datetime] = Query(None, description="Filter start date"),
    end_date: Optional[datetime] = Query(None, description="Filter end date"),
):
    """
    Get paginated chat conversation history with optional date filtering.
    
    Args:
        page: Page number (1-indexed), minimum 1
        limit: Number of results per page, between 1 and 100
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
    
    Returns:
        ChatLogResponse with paginated thread information
    """
    page, limit = validate_pagination(page, limit)
    return await store.list_chatlogs(page, limit, start_date, end_date)


@router.get("/{thread_id}")
async def get_chat_thread(thread_id: str):
    """
    Get complete conversation history for a specific thread.
    
    Args:
        thread_id: The thread identifier
    
    Returns:
        List of ChatLog objects for the thread
    
    Raises:
        HTTPException: 404 if thread not found
    """
    conversation = await store.get_chat_thread(thread_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    return conversation