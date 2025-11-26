"""Shared Pydantic models for chat logging functionality."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Represents a single chat message with optional context."""

    text: str
    context: Optional[Dict] = Field(default_factory=dict)

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {"text": "Hello", "context": {"user_id": "123"}}
        }


class ChatThreadInfo(BaseModel):
    """Metadata for a chat thread."""

    thread_id: str
    date: datetime

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {"thread_id": "thread_001", "date": "2024-01-01T00:00:00"}
        }


class BotMessage(BaseModel):
    """Represents a bot response message."""

    text: str

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {"example": {"text": "How can I help you?"}}


class ChatLog(BaseModel):
    """Complete chat log entry with user and bot messages."""

    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Optional[Dict] = Field(default_factory=dict)

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "user_message": {"text": "Hello", "context": {}},
                "bot_message": [{"text": "Hi there"}],
                "date": "2024-01-01T00:00:00",
                "context": {},
            }
        }


class ChatLogResponse(BaseModel):
    """Paginated response for chat logs."""

    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "total": 100,
                "page": 1,
                "limit": 10,
                "conversations": [
                    {"thread_id": "thread_001", "date": "2024-01-01T00:00:00"}
                ],
            }
        }