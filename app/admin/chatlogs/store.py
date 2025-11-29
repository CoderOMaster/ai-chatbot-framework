from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING

from app.config import app_config
from app.database import CollectionGetter, create_collection_getter_from_config
from .schemas import ChatLog, ChatLogResponse, ChatThreadInfo

CHATLOG_COLLECTION_NAME = "state"
_DEFAULT_COLLECTION_GETTER: CollectionGetter = create_collection_getter_from_config(app_config)


def _get_chatlogs_collection(
    collection_getter: Optional[CollectionGetter] = None,
) -> AsyncIOMotorCollection:
    """Return the collection used to store chat logs, honoring overrides."""

    getter = collection_getter or _DEFAULT_COLLECTION_GETTER
    return getter(CHATLOG_COLLECTION_NAME)


def _build_date_range_query(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> Dict[str, Any]:
    """Construct a MongoDB date range filter when start or end dates are provided."""

    date_query: Dict[str, datetime] = {}
    if start_date:
        date_query["$gte"] = start_date
    if end_date:
        date_query["$lte"] = end_date
    if not date_query:
        return {}

    return {"date": date_query}


def _count_threads_pipeline(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the aggregation pipeline that counts unique chat threads."""

    return [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]


def _conversation_paging_pipeline(
    query: Dict[str, Any],
    skip: int,
    limit: int,
) -> List[Dict[str, Any]]:
    """Build the pipeline that returns paged thread summaries ordered by latest date."""

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


def _project_chat_thread_info(document: Dict[str, Any]) -> ChatThreadInfo:
    """Map a grouped aggregation result to the ChatThreadInfo schema."""

    return ChatThreadInfo(thread_id=document["thread_id"], date=document["date"])


def _map_chat_log_document(document: Dict[str, Any]) -> ChatLog:
    """Convert a raw chat log document to the Pydantic ChatLog model."""

    return ChatLog(
        user_message=document["user_message"],
        bot_message=document.get("bot_message", []),
        date=document["date"],
        context=document.get("context", {}),
    )


async def ensure_chatlog_indexes(
    collection_getter: Optional[CollectionGetter] = None,
) -> None:
    """Ensure indexes for read-heavy chat log queries exist."""

    collection = _get_chatlogs_collection(collection_getter)
    await collection.create_index(
        [("thread_id", ASCENDING)],
        name="chatlogs_thread_id_idx",
    )
    await collection.create_index(
        [("date", DESCENDING)],
        name="chatlogs_date_idx",
    )


async def list_chatlogs(
    page: int = 1,
    limit: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    collection_getter: Optional[CollectionGetter] = None,
) -> ChatLogResponse:
    """List paged chat threads optionally filtered by date range."""

    skip = max((page - 1) * limit, 0)
    collection = _get_chatlogs_collection(collection_getter)
    query = _build_date_range_query(start_date, end_date)

    total_pipeline = _count_threads_pipeline(query)
    result = await collection.aggregate(total_pipeline).to_list(length=1)
    total = result[0]["total"] if result else 0

    conversation_pipeline = _conversation_paging_pipeline(query, skip, limit)
    conversations: List[ChatThreadInfo] = []
    async for document in collection.aggregate(conversation_pipeline):
        conversations.append(_project_chat_thread_info(document))

    return ChatLogResponse(
        total=total,
        page=page,
        limit=limit,
        conversations=conversations,
    )


async def get_chat_thread(
    thread_id: str,
    collection_getter: Optional[CollectionGetter] = None,
) -> Optional[List[ChatLog]]:
    """Return the conversation history for a given thread id."""

    collection = _get_chatlogs_collection(collection_getter)
    cursor = collection.find({"thread_id": thread_id}).sort("date", ASCENDING)
    messages = await cursor.to_list(length=None)

    if not messages:
        return None

    return [_map_chat_log_document(message) for message in messages]