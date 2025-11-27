from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from .schemas import (
    ChatLog,
    ChatLogResponse,
    ChatThreadInfo,
    ChatMessage,
    BotMessage,
)


def _build_count_pipeline(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build aggregation pipeline that counts unique threads matching query."""
    return [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]


def _build_list_pipeline(
    query: Dict[str, Any], limit: int, cursor: Optional[str] = None, use_skip: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Build aggregation pipeline that returns the latest document per thread.

    The pipeline sorts documents by _id (ObjectId) descending to leverage the
    default _id index for efficient range queries. After sorting it groups by
    thread_id and picks the first document (the newest for that thread).

    If a cursor (stringified ObjectId) is provided the grouped results are
    filtered to only include groups with a latest_doc_id < cursor for paging.
    """
    pipeline: List[Dict[str, Any]] = [{"$match": query}, {"$sort": {"_id": -1}}]

    # Group by thread_id taking the first (latest) document's id and date
    pipeline.append(
        {
            "$group": {
                "_id": "$thread_id",
                "thread_id": {"$first": "$thread_id"},
                "latest_doc_id": {"$first": "$_id"},
                "date": {"$first": "$date"},
            }
        }
    )

    # Sort groups by latest_doc_id descending (newest threads first)
    pipeline.append({"$sort": {"latest_doc_id": -1}})

    # If cursor provided, filter groups to those older than the cursor
    if cursor:
        try:
            oid = ObjectId(cursor)
            pipeline.append({"$match": {"latest_doc_id": {"$lt": oid}}})
        except Exception:
            # Invalid cursor provided; ignore and return from beginning
            pass

    # If use_skip provided (backwards-compatibility with page-based callers), apply skip
    if use_skip and use_skip > 0:
        pipeline.append({"$skip": use_skip})

    # We request limit results; callers may use limit+1 if they want to detect next page.
    pipeline.append({"$limit": limit})

    return pipeline


async def list_chatlogs(
    collection: AsyncIOMotorCollection,
    page: int = 1,
    limit: int = 10,
    cursor: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ChatLogResponse:
    """List chat threads with cursor-based pagination.

    Parameters
    - collection: injected AsyncIOMotorCollection instance (no global client use)
    - page: retained for backwards compatibility; when >1 and no cursor is
      provided it will fall back to skip-based pagination (less efficient).
    - limit: number of threads to return
    - cursor: optional stringified ObjectId used as a pagination cursor; when
      provided, threads with latest_doc_id < cursor are returned.
    - start_date / end_date: optional date range applied to the underlying
      message documents before grouping by thread.

    Returns a ChatLogResponse containing thread summaries. This function maps
    raw aggregation documents into ChatThreadInfo DTOs so internal field names
    are not leaked.
    """
    # Build base query for date range filtering
    query: Dict[str, Any] = {}
    if start_date or end_date:
        query["date"] = {}
        if start_date:
            query["date"]["$gte"] = start_date
        if end_date:
            query["date"]["$lte"] = end_date

    # Count total unique threads (may be expensive but kept for compatibility)
    count_pipeline = _build_count_pipeline(query)
    result = await collection.aggregate(count_pipeline).to_list(length=1)
    total = result[0]["total"] if result else 0

    # Determine skip for backward-compatible page-based callers
    skip = (page - 1) * limit if page and page > 1 and not cursor else 0

    list_pipeline = _build_list_pipeline(query, limit, cursor, use_skip=skip)

    conversations: List[ChatThreadInfo] = []
    async for doc in collection.aggregate(list_pipeline):
        # Map raw aggregation document into the DTO; don't expose internal keys
        conversations.append(
            ChatThreadInfo(thread_id=doc["thread_id"], date=doc.get("date"))
        )

    return ChatLogResponse(total=total, page=page, limit=limit, conversations=conversations)


async def get_chat_thread(collection: AsyncIOMotorCollection, thread_id: str) -> List[ChatLog]:
    """Return the full conversation for a thread as a list of ChatLog DTOs.

    The collection is injected to support sharded deployments and testing.
    Returns an empty list when no messages are found.
    """
    cursor = collection.find({"thread_id": thread_id}).sort("_id", 1)
    messages = await cursor.to_list(length=None)

    if not messages:
        return []

    chat_logs: List[ChatLog] = []
    for msg in messages:
        # Map user message and bot messages into DTOs to avoid leaking internal structure
        user_raw = msg.get("user_message", {})
        if isinstance(user_raw, dict):
            user_message = ChatMessage(text=user_raw.get("text", ""), context=user_raw.get("context", {}))
        else:
            # If stored as a plain string
            user_message = ChatMessage(text=str(user_raw), context={})

        bot_raw = msg.get("bot_message", [])
        bot_messages: List[BotMessage] = []
        if isinstance(bot_raw, list):
            for b in bot_raw:
                if isinstance(b, dict):
                    bot_messages.append(BotMessage(text=b.get("text", "")))
                else:
                    bot_messages.append(BotMessage(text=str(b)))
        else:
            bot_messages.append(BotMessage(text=str(bot_raw)))

        chat_logs.append(
            ChatLog(
                user_message=user_message,
                bot_message=bot_messages,
                date=msg.get("date"),
                context=msg.get("context", {}),
            )
        )

    return chat_logs