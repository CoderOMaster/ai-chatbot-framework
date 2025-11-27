from typing import Text, Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from datetime import datetime
from app.bot.memory.models import State
from app.bot.memory import MemorySaver


class MemorySaverMongo(MemorySaver):
    """
    MemorySaverMongo implements the MemorySaver interface for MongoDB using an
    injected AsyncIOMotorClient. It creates helpful indexes on enter and can
    optionally manage the lifecycle of the provided client.

    Important security note: persisted blobs omit NLU internals and raw
    message payloads to avoid leaking sensitive information.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        *,
        manage_client: bool = False,
        retention_seconds: Optional[int] = 30 * 24 * 3600,
    ) -> None:
        """
        Args:
            client: Injected AsyncIOMotorClient instance (dependency injection).
            manage_client: If True the instance will close the client on exit.
            retention_seconds: If provided (>0) a TTL index will be created on the
                stored state's `date` field to automatically remove old entries.
                Pass None or 0 to disable TTL index creation.
        """
        self.client: AsyncIOMotorClient = client
        self.manage_client = manage_client
        self.retention_seconds = int(retention_seconds) if retention_seconds else None
        self.db = client.get_database("chatbot")
        self.collection: AsyncIOMotorCollection = self.db.get_collection("state")
        self._indexes_created = False

    async def __aenter__(self) -> "MemorySaverMongo":
        """Prepare the collection by creating indexes. This is executed when used
        as `async with MemorySaverMongo(...)`.
        """
        # Create indexes once per instance. These operations are idempotent.
        if not self._indexes_created:
            # Index to efficiently query by thread_id and recent date
            await self.collection.create_index([("thread_id", 1), ("date", -1)])

            # Optional TTL index to auto-expire old state documents
            if self.retention_seconds and self.retention_seconds > 0:
                # expireAfterSeconds expects an int number of seconds
                await self.collection.create_index("date", expireAfterSeconds=self.retention_seconds)

            # Additional index for analytics queries (lookup by thread_id)
            await self.collection.create_index("thread_id")

            self._indexes_created = True

        return self

    async def __aexit__(self, exc_type: Any = None, exc: Any = None, tb: Any = None) -> None:
        """Clean up resources. Will close the injected client only if
        manage_client was True to avoid closing shared clients.
        """
        if self.manage_client:
            # Motor client provides a close() method
            try:
                self.client.close()
            except Exception:
                # Best-effort close; do not raise to avoid masking original errors
                pass

    def _safe_state_dict(self, state: State) -> Dict[str, Any]:
        """
        Serialize only a subset of State fields that are considered safe for
        persistence and analytics. This excludes NLU internals and raw message
        payloads (user_message, bot_message) to avoid leaking sensitive data.
        """
        payload = {
            "schema_version": getattr(state, "date", None) and state.to_dict().get("schema_version") or 1,
            "thread_id": state.thread_id,
            # Keep conversational shape and context but avoid raw NLU payloads
            "context": dict(state.context) if state.context is not None else {},
            "intent": dict(state.intent) if state.intent is not None else {},
            "parameters": list(state.parameters) if state.parameters is not None else [],
            "extracted_parameters": dict(state.extracted_parameters) if state.extracted_parameters is not None else {},
            "missing_parameters": list(state.missing_parameters) if state.missing_parameters is not None else [],
            "complete": bool(state.complete),
            "current_node": state.current_node,
            # Persist a timestamp for TTL and ordering
            "date": getattr(state, "date", datetime.utcnow()),
        }
        return payload

    async def save(self, thread_id: Text, state: State) -> None:
        """Persist a safe serialized snapshot of the provided State for thread_id.

        The stored document deliberately omits NLU internals and raw message
        payloads. Use .snapshot() if a full immutable blob is required elsewhere.
        """
        doc = self._safe_state_dict(state)
        # Ensure thread_id is consistent with provided arg
        doc["thread_id"] = thread_id
        await self.collection.insert_one(doc)

    async def get(self, thread_id: Text) -> Optional[State]:
        """Return the latest stored State for thread_id or None if absent.

        This method projects out known sensitive fields as an extra-safety.
        """
        projection = {"_id": 0, "nlu": 0, "user_message": 0, "bot_message": 0}
        result = await self.collection.find_one(
            {"thread_id": thread_id}, projection, sort=[("date", -1)]
        )
        if result:
            return State.from_dict(result)
        return None

    async def get_all(self, thread_id: Text) -> List[State]:
        """Return all stored State entries for thread_id ordered from newest to oldest."""
        cursor = self.collection.find({"thread_id": thread_id}, sort=[("date", -1)])
        results = await cursor.to_list(length=None)
        return [State.from_dict(r) for r in results]

    async def bulk_get(self, thread_ids: List[Text]) -> List[State]:
        """Return the most recent State for each thread_id in thread_ids.

        This is implemented with an aggregation pipeline that sorts by date and
        picks the first document per thread_id which makes it efficient for
        analytics queries.
        """
        if not thread_ids:
            return []

        pipeline = [
            {"$match": {"thread_id": {"$in": thread_ids}}},
            {"$sort": {"date": -1}},
            {"$group": {"_id": "$thread_id", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
            {"$project": {"_id": 0, "nlu": 0, "user_message": 0, "bot_message": 0}},
        ]

        cursor = self.collection.aggregate(pipeline)
        docs = await cursor.to_list(length=None)
        return [State.from_dict(d) for d in docs]