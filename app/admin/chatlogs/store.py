from typing import List, Optional
from datetime import datetime
from app.common.config import Settings
from app.common.database import get_db
from .schemas import ChatLog, ChatLogResponse, ChatThreadInfo

_settings = Settings()


async def _collection():
    db = await get_db(_settings)
    return db["state"]


async def list_chatlogs(
    page: int = 1,
    limit: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ChatLogResponse:
    skip = (page - 1) * limit

    col = await _collection()

    # Build query filter
    query = {}
    if start_date or end_date:
        query["date"] = {}
        if start_date:
            query["date"]["$gte"] = start_date
        if end_date:
            query["date"]["$lte"] = end_date

    # Get total count of unique threads for pagination
    pipeline = [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]
    result = await col.aggregate(pipeline).to_list(1)
    total = result[0]["total"] if result else 0

    # Get paginated results grouped by thread_id with latest date
    pipeline = [
        {"$match": query},
        {"$sort": {"date": -1}},
        {
            "$group": {
                "_id": "$thread_id",
                "thread_id": {"$first": "$thread_id"},
                "date": {"$first": "$date"},
            }
        },
        {"$sort": {"date": -1}},
        {"$skip": skip},
        {"$limit": limit},
    ]

    conversations = []
    async for doc in col.aggregate(pipeline):
        conversations.append(
            ChatThreadInfo(thread_id=doc["thread_id"], date=doc["date"])
        )

    return ChatLogResponse(
        total=total, page=page, limit=limit, conversations=conversations
    )


async def get_chat_thread(thread_id: str) -> List[ChatLog]:
    """Get complete conversation history for a specific thread"""

    col = await _collection()
    cursor = col.find({"thread_id": thread_id}).sort("date", 1)
    messages = await cursor.to_list(length=None)

    if not messages:
        return None

    chat_logs = []
    for msg in messages:
        chat_logs.append(
            ChatLog(
                user_message=msg["user_message"],
                bot_message=msg["bot_message"],
                date=msg["date"],
                context=msg.get("context", {}),
            )
        )

    return chat_logs