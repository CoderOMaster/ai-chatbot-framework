from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Represents a user's chat message with optional contextual metadata."""

    text: str
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatThreadInfo(BaseModel):
    """Lightweight thread information used in listings and pagination."""

    thread_id: str
    date: datetime


class BotMessage(BaseModel):
    """Represents a single message from the bot."""

    text: str


class ChatLog(BaseModel):
    """Full conversation log between a user and bot.

    Note: context defaults to an empty dict via Field(default_factory=dict)
    to avoid mutable default pitfalls.
    """

    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatLogResponse(BaseModel):
    """Paginated response for chat threads."""

    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]


# Lightweight DTOs for streaming chat threads in chunks. These are intentionally
# minimal to allow streaming large threads without loading full payloads.
class StreamMessageDTO(BaseModel):
    """Minimal representation of a message for streaming purposes."""

    sender: str  # e.g. "user" or "bot"
    text: str
    date: Optional[datetime] = None


class ChatThreadChunkDTO(BaseModel):
    """A chunk of messages from a single chat thread suitable for streaming.

    chunk_index starts at 0 and is_last indicates whether this is the final
    chunk for the thread.
    """

    thread_id: str
    chunk_index: int = 0
    is_last: bool = False
    messages: List[StreamMessageDTO]