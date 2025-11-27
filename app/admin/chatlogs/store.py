from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
import hashlib
import os

from app.database import client
from .schemas import ChatLog, ChatLogResponse, ChatThreadInfo

# Initialize MongoDB collection
collection = client["chatbot"]["state"]
archive_collection = client["chatbot"]["state_archive"]


async def setup_indexes() -> None:
    """Initialize TTL and search indexes for optimal performance."""
    # TTL index for automatic data retention (configurable via environment)
    ttl_days = int(os.getenv("LOG_RETENTION_DAYS", "90"))
    await collection.create_index(
        "date",
        expireAfterSeconds=ttl_days * 86400,
        background=True
    )
    
    # Compound index for efficient thread queries
    await collection.create_index(
        [("thread_id", 1), ("date", -1)],
        background=True
    )
    
    # Text index for search capabilities
    await collection.create_index(
        [("user_message.text", "text"), ("bot_message.text", "text")],
        background=True
    )
    
    # Index for date range queries
    await collection.create_index(
        [("date", -1)],
        background=True
    )


async def archive_old_logs(days_threshold: int = 30) -> int:
    """
    Archive chat logs older than threshold to archive collection.
    
    Args:
        days_threshold: Number of days to keep in active collection
        
    Returns:
        Number of documents archived
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
    
    # Find documents to archive
    docs_to_archive = await collection.find(
        {"date": {"$lt": cutoff_date}}
    ).to_list(length=None)
    
    if not docs_to_archive:
        return 0
    
    # Insert into archive collection
    if docs_to_archive:
        await archive_collection.insert_many(docs_to_archive)
    
    # Remove from active collection
    result = await collection.delete_many({"date": {"$lt": cutoff_date}})
    
    return result.deleted_count


def _anonymize_message(text: str, hash_length: int = 8) -> str:
    """
    Anonymize sensitive data in messages using hashing.
    
    Args:
        text: Original message text
        hash_length: Length of hash to use for anonymization
        
    Returns:
        Anonymized message text
    """
    # Simple anonymization - replace email-like patterns with hashes
    import re
    
    def hash_match(match):
        original = match.group(0)
        hash_val = hashlib.md5(original.encode()).hexdigest()[:hash_length]
        return f"[ANON_{hash_val}]"
    
    # Anonymize email-like patterns
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', hash_match, text)
    
    # Anonymize phone-like patterns
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', hash_match, text)
    
    return text


async def list_chatlogs(
    page: int = 1,
    limit: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    cursor: Optional[str] = None,
    search_query: Optional[str] = None,
    anonymize: bool = False,
) -> ChatLogResponse:
    """
    List chat logs with cursor-based pagination and optional search.
    
    Args:
        page: Page number (for offset-based pagination)
        limit: Number of results per page
        start_date: Filter logs after this date
        end_date: Filter logs before this date
        cursor: Cursor for cursor-based pagination (base64 encoded ObjectId)
        search_query: Full-text search query
        anonymize: Whether to anonymize sensitive data in results
        
    Returns:
        ChatLogResponse with paginated results
    """
    # Build query filter
    query: Dict[str, Any] = {}
    
    # Date range filter
    if start_date or end_date:
        query["date"] = {}
        if start_date:
            query["date"]["$gte"] = start_date
        if end_date:
            query["date"]["$lte"] = end_date
    
    # Full-text search filter
    if search_query:
        query["$text"] = {"$search": search_query}
    
    # Cursor-based pagination
    if cursor:
        try:
            cursor_id = ObjectId(cursor)
            query["_id"] = {"$lt": cursor_id}
        except Exception:
            pass  # Invalid cursor, ignore
    
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
        {"$sort": {"_id": -1}},  # Use _id for cursor-based pagination
        {
            "$group": {
                "_id": "$thread_id",
                "thread_id": {"$first": "$thread_id"},
                "date": {"$first": "$date"},
                "last_id": {"$first": "$_id"},
            }
        },
        {"$sort": {"date": -1}},
        {"$skip": (page - 1) * limit},
        {"$limit": limit},
    ]
    
    conversations = []
    next_cursor = None
    
    async for doc in collection.aggregate(pipeline):
        conversations.append(
            ChatThreadInfo(thread_id=doc["thread_id"], date=doc["date"])
        )
        # Store last document ID for cursor
        if not next_cursor:
            next_cursor = str(doc["last_id"])
    
    response = ChatLogResponse(
        total=total, page=page, limit=limit, conversations=conversations
    )
    
    # Add cursor to response if available (would need schema update)
    if next_cursor:
        response.next_cursor = next_cursor  # type: ignore
    
    return response


async def get_chat_thread(
    thread_id: str,
    anonymize: bool = False,
) -> Optional[List[ChatLog]]:
    """
    Get complete conversation history for a specific thread.
    
    Args:
        thread_id: The thread ID to retrieve
        anonymize: Whether to anonymize sensitive data
        
    Returns:
        List of ChatLog entries or None if thread not found
    """
    cursor = collection.find({"thread_id": thread_id}).sort("date", 1)
    messages = await cursor.to_list(length=None)
    
    if not messages:
        return None
    
    chat_logs = []
    for msg in messages:
        user_text = msg.get("user_message", {})
        if isinstance(user_text, dict):
            user_text = user_text.get("text", "")
        
        if anonymize:
            user_text = _anonymize_message(user_text)
        
        # Handle bot_message as list or string
        bot_messages = msg.get("bot_message", [])
        if isinstance(bot_messages, str):
            bot_messages = [{"text": bot_messages}]
        elif not isinstance(bot_messages, list):
            bot_messages = [{"text": str(bot_messages)}]
        
        if anonymize:
            bot_messages = [
                {"text": _anonymize_message(b.get("text", "") if isinstance(b, dict) else str(b))}
                for b in bot_messages
            ]
        
        chat_logs.append(
            ChatLog(
                user_message={"text": user_text, "context": msg.get("context", {})},
                bot_message=bot_messages,
                date=msg["date"],
                context=msg.get("context", {}),
            )
        )
    
    return chat_logs


async def search_chatlogs(
    query: str,
    limit: int = 20,
    skip: int = 0,
) -> List[Dict[str, Any]]:
    """
    Full-text search across chat logs.
    
    Args:
        query: Search query string
        limit: Maximum results to return
        skip: Number of results to skip
        
    Returns:
        List of matching chat log documents
    """
    pipeline = [
        {"$match": {"$text": {"$search": query}}},
        {"$sort": {"score": {"$meta": "textScore"}}},
        {"$skip": skip},
        {"$limit": limit},
    ]
    
    results = await collection.aggregate(pipeline).to_list(length=limit)
    return results


async def get_thread_statistics(
    thread_id: str,
) -> Dict[str, Any]:
    """
    Get aggregated statistics for a chat thread.
    
    Args:
        thread_id: The thread ID to analyze
        
    Returns:
        Dictionary with thread statistics
    """
    pipeline = [
        {"$match": {"thread_id": thread_id}},
        {
            "$group": {
                "_id": "$thread_id",
                "message_count": {"$sum": 1},
                "first_message": {"$min": "$date"},
                "last_message": {"$max": "$date"},
                "avg_context_size": {"$avg": {"$strLenCP": {"$toString": "$context"}}},
            }
        },
    ]
    
    result = await collection.aggregate(pipeline).to_list(1)
    return result[0] if result else {}


async def delete_thread(thread_id: str) -> int:
    """
    Delete all messages for a specific thread (GDPR compliance).
    
    Args:
        thread_id: The thread ID to delete
        
    Returns:
        Number of documents deleted
    """
    result = await collection.delete_many({"thread_id": thread_id})
    return result.deleted_count