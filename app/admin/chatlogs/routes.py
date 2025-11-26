from fastapi import APIRouter, HTTPException
from typing import List, Optional
from datetime import datetime
from app.admin.chatlogs.store import list_chatlogs, get_chat_thread
from shared.models.chatlogs import ChatLog, ChatLogResponse

router = APIRouter(prefix="/chatlogs", tags=["chatlogs"])


@router.get("/", response_model=ChatLogResponse)
async def list_chatlogs_handler(
    page: int = 1,
    limit: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ChatLogResponse:
    """Get paginated chat conversation history with optional date filtering"""
    return await list_chatlogs(page, limit, start_date, end_date)


@router.get("/{thread_id}", response_model=List[ChatLog])
async def get_chat_thread_handler(thread_id: str) -> List[ChatLog]:
    """Get complete conversation history for a specific thread"""
    conversation = await get_chat_thread(thread_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation