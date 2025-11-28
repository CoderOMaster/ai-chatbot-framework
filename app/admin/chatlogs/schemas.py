from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Represents a single message submitted by a user in a chat session."""

    text: str
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatThreadInfo(BaseModel):
    """Metadata about a chat conversation used for pagination and listings."""

    thread_id: str
    date: datetime


class BotMessage(BaseModel):
    """Represents a single message returned by the assistant or bot."""

    text: str


class ChatLog(BaseModel):
    """Stores a single conversation between a user and the bot."""

    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatLogResponse(BaseModel):
    """Response payload returned when listing conversations."""

    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]