from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional
from datetime import datetime


class ChatMessage(BaseModel):
    """Represents a single chat message with optional context."""
    text: str
    context: Optional[Dict] = Field(default_factory=dict)


class ChatThreadInfo(BaseModel):
    """Represents chat thread metadata for list views."""
    thread_id: str
    date: datetime

    @field_validator('date')
    @classmethod
    def validate_date(cls, v: datetime) -> datetime:
        """Ensure date is a valid datetime object."""
        if not isinstance(v, datetime):
            raise ValueError('date must be a datetime object')
        return v


class BotMessage(BaseModel):
    """Represents a single bot message response."""
    text: str


class ChatLog(BaseModel):
    """Represents a complete chat log entry with user and bot messages."""
    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Optional[Dict] = Field(default_factory=dict)

    @field_validator('date')
    @classmethod
    def validate_date(cls, v: datetime) -> datetime:
        """Ensure date is a valid datetime object."""
        if not isinstance(v, datetime):
            raise ValueError('date must be a datetime object')
        return v


class ChatLogListView(BaseModel):
    """Represents a chat log in list view format (minimal data)."""
    thread_id: str
    date: datetime
    user_message_preview: str = Field(max_length=100)

    @field_validator('date')
    @classmethod
    def validate_date(cls, v: datetime) -> datetime:
        """Ensure date is a valid datetime object."""
        if not isinstance(v, datetime):
            raise ValueError('date must be a datetime object')
        return v


class ChatLogDetailView(BaseModel):
    """Represents a chat log in detail view format (full data)."""
    thread_id: str
    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Optional[Dict] = Field(default_factory=dict)

    @field_validator('date')
    @classmethod
    def validate_date(cls, v: datetime) -> datetime:
        """Ensure date is a valid datetime object."""
        if not isinstance(v, datetime):
            raise ValueError('date must be a datetime object')
        return v


class ChatLogResponse(BaseModel):
    """Represents paginated chat log response."""
    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]