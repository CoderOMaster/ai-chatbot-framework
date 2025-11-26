from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime


class ChatMessage(BaseModel):
    text: str
    context: Optional[Dict] = Field(default_factory=dict)


class ChatThreadInfo(BaseModel):
    thread_id: str
    date: datetime


class BotMessage(BaseModel):
    text: str


class ChatLog(BaseModel):
    user_message: ChatMessage
    bot_message: List[BotMessage]
    date: datetime
    context: Optional[Dict] = Field(default_factory=dict)


class ChatLogResponse(BaseModel):
    total: int
    page: int
    limit: int
    conversations: List[ChatThreadInfo]