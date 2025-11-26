from typing import List, Optional
from datetime import datetime
from app.database import client
from .schemas import ChatLog, ChatLogResponse, ChatThreadInfo

# Initialize MongoDB collection
collection = client["chatbot"]["state"]

# Default query parameters for efficient pagination
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_PROJECTION = {"thread_id": 1, "date": 1, "user_message": 1, "bot_message": 1, "context": 1}


async def ensure_indexes() -> None:
    """Ensure required indexes exist for efficient querying."""
    await collection.create_index("thread_id")
    await collection.create_index("date")
    await collection.create_index([("thread_id", 1), ("date", -1)])


async def list_chatlogs(
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ChatLogResponse:
    """
    List chat threads with pagination and optional date filtering.
    
    Args:
        page: Page number (1-indexed)
        limit: Number of results per page (capped at MAX_LIMIT)
        start_date: Optional start date filter
        end_date: Optional end date filter
    
    Returns:
        ChatLogResponse with paginated thread information
    """
    # Enforce limit constraints
    limit = min(limit, MAX_LIMIT)
    skip = (page - 1) * limit

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
    result = await collection.aggregate(pipeline).to_list(1)
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
    async for doc in collection.aggregate(pipeline):
        conversations.append(
            ChatThreadInfo(thread_id=doc["thread_id"], date=doc["date"])
        )

    return ChatLogResponse(
        total=total, page=page, limit=limit, conversations=conversations
    )


async def get_chat_thread(
    thread_id: str,
    projection: Optional[dict] = None,
) -> Optional[List[ChatLog]]:
    """
    Get complete conversation history for a specific thread.
    
    Args:
        thread_id: The thread identifier
        projection: Optional MongoDB projection dict to limit returned fields
    
    Returns:
        List of ChatLog objects or None if thread not found
    """
    if projection is None:
        projection = DEFAULT_PROJECTION

    cursor = collection.find(
        {"thread_id": thread_id},
        projection=projection
    ).sort("date", 1)
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