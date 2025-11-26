"""Shared Pydantic schemas for chatlog serialization.

These models are intentionally lightweight and dependency-free so they can be
used across services (monolith and chatlogs microservices/Lambdas).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A message sent by a user in a conversation.

    Attributes:
        text: The message text.
        context: Optional contextual metadata for the message.
    """

    text: str
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatThreadInfo(BaseModel):
    """Metadata for a conversation/thread.

    Attributes:
        thread_id: Unique identifier for the thread.
        date: Timestamp for the thread creation or last activity.
    """

    thread_id: str
    date: datetime


class BotMessage(BaseModel):
    """A message produced by the bot.

    Attributes:
        text: The message text from the bot.
    """

    text: str


# Backwards compatibility: some code may have referenced the misspelled name
# `BotNessage`. Keep a compatibility alias to avoid breaking imports.
BotNessage = BotMessage


class ChatLog(BaseModel):
    """A single chat log containing user and bot messages.

    Attributes:
        user_message: The message from the user.
        bot_message: One or more messages produced by the bot.
        date: Timestamp for the log entry.
        context: Optional contextual metadata for the log.
    """

    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatLogResponse(BaseModel):
    """Paged response containing chat thread info.

    Attributes:
        total: Total number of threads available.
        page: Current page number.
        limit: Number of items per page.
        conversations: List of conversation/thread metadata.
    """

    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]