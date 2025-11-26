from typing import List, Optional, Dict, Any
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorCollection

from app.database import get_collection
from .schemas import ChatLog, ChatLogResponse, ChatThreadInfo

# Default collection name used by this module. Callers may override by
# passing an explicit collection instance to functions (dependency injection
# friendly and suitable for unit tests or standalone services).
DEFAULT_COLLECTION_NAME = "state"

# Internal flag to avoid re-creating indexes repeatedly.
_indexes_ensured = False


def _build_date_query(start_date: Optional[datetime], end_date: Optional[datetime]) -> Dict[str, Any]:
    """Construct the MongoDB date filter for aggregation pipelines.

    Returns an empty dict when no date bounds are provided.
    """
    if not start_date and not end_date:
        return {}

    date_filter: Dict[str, Any] = {}
    if start_date:
        date_filter["$gte"] = start_date
    if end_date:
        date_filter["$lte"] = end_date

    return {"date": date_filter}


def _pipeline_count_threads(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Aggregation pipeline to count unique thread_ids matching the query."""
    return [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]


def _pipeline_list_threads(query: Dict[str, Any], skip: int, limit: int) -> List[Dict[str, Any]]:
    """Aggregation pipeline to return paginated thread metadata (latest date per thread)."""
    return [
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


def _thread_projection() -> Dict[str, int]:
    """Projection used when reading full thread messages from the collection.

    Keeps the returned shape stable and avoids leaking internal _id fields.
    """
    return {"_id": 0, "user_message": 1, "bot_message": 1, "date": 1, "context": 1, "thread_id": 1}


async def ensure_indexes(collection: Optional[AsyncIOMotorCollection] = None) -> None:
    """Ensure recommended read indexes exist on the collection.

    Indexes: thread_id (ascending), date (descending). Callers may await this
    during startup; the function is idempotent.
    """
    global _indexes_ensured
    if _indexes_ensured:
        return

    if collection is None:
        collection = get_collection(DEFAULT_COLLECTION_NAME)

    # thread_id ascending for efficient thread lookups
    await collection.create_index([("thread_id", 1)], background=True)
    # date descending to support sorting by latest activity
    await collection.create_index([("date", -1)], background=True)

    _indexes_ensured = True


async def list_chatlogs(
    page: int = 1,
    limit: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    collection: Optional[AsyncIOMotorCollection] = None,
) -> ChatLogResponse:
    """Return a paginated list of conversation threads.

    This function is read-only and accepts an optional collection instance to
    make dependency injection simple for unit tests and microservices. If no
    collection is provided the module will resolve the default collection via
    app.database.get_collection.
    """
    if collection is None:
        collection = get_collection(DEFAULT_COLLECTION_NAME)

    # Ensure indexes exist (no-op after first run).
    await ensure_indexes(collection)

    skip = (page - 1) * limit

    # Build query filter
    query = _build_date_query(start_date, end_date)

    # Get total count of unique threads for pagination
    count_pipeline = _pipeline_count_threads(query)
    result = await collection.aggregate(count_pipeline).to_list(1)
    total = result[0]["total"] if result else 0

    # Get paginated results grouped by thread_id with latest date
    list_pipeline = _pipeline_list_threads(query, skip, limit)

    conversations: List[ChatThreadInfo] = []
    async for doc in collection.aggregate(list_pipeline):
        conversations.append(ChatThreadInfo(thread_id=doc["thread_id"], date=doc["date"]))

    return ChatLogResponse(total=total, page=page, limit=limit, conversations=conversations)


async def get_chat_thread(
    thread_id: str, collection: Optional[AsyncIOMotorCollection] = None
) -> Optional[List[ChatLog]]:
    """Get the complete conversation history for a specific thread.

    Returns None when the thread does not exist. Callers may provide an
    AsyncIOMotorCollection to avoid implicit resolution via get_collection().
    """
    if collection is None:
        collection = get_collection(DEFAULT_COLLECTION_NAME)

    await ensure_indexes(collection)

    cursor = collection.find({"thread_id": thread_id}, _thread_projection()).sort("date", 1)
    messages = await cursor.to_list(length=None)

    if not messages:
        return None

    chat_logs: List[ChatLog] = []
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