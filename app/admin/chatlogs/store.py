from typing import List, Optional
from datetime import datetime
from shared.database import client
from shared.models.chatlogs import ChatLog, ChatLogResponse, ChatThreadInfo

# Initialize MongoDB collection
collection = client["chatbot"]["state"]

# Pagination limits
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 10


def _validate_date_range(
    start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
) -> None:
    """Validate date range parameters.
    
    Args:
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
        
    Raises:
        ValueError: If end_date is before start_date
    """
    if start_date and end_date and end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date")


async def list_chatlogs(
    page: int = 1,
    limit: int = DEFAULT_PAGE_SIZE,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ChatLogResponse:
    """List chat logs with pagination and optional date range filtering.
    
    Args:
        page: Page number (1-indexed)
        limit: Number of results per page (max 100)
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
        
    Returns:
        ChatLogResponse with paginated results
        
    Raises:
        ValueError: If date range is invalid or limit exceeds maximum
    """
    # Validate pagination limit
    if limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit cannot exceed {MAX_PAGE_SIZE}")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if page < 1:
        raise ValueError("page must be at least 1")
    
    # Validate date range
    _validate_date_range(start_date, end_date)
    
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
    # Index hint: thread_id, date
    pipeline = [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]
    result = await collection.aggregate(pipeline).to_list(1)
    total = result[0]["total"] if result else 0

    # Get paginated results grouped by thread_id with latest date
    # Index hint: date (descending), thread_id
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


async def get_chat_thread(thread_id: str) -> Optional[List[ChatLog]]:
    """Get complete conversation history for a specific thread.
    
    Args:
        thread_id: The thread identifier to retrieve
        
    Returns:
        List of ChatLog entries for the thread, or None if not found
    """
    # Index hint: thread_id, date (ascending)
    cursor = collection.find({"thread_id": thread_id}).sort("date", 1)
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