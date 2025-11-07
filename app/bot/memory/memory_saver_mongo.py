from typing import Text, Optional, List
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.bot.memory.models import State
from app.bot.memory import MemorySaver


class MemorySaverMongo(MemorySaver):
    """
    MemorySaverMongo implements the MemorySaver interface for MongoDB.
    Now depends on an injected database or client, rather than importing singletons.

    You can pass either an AsyncIOMotorDatabase instance or an AsyncIOMotorClient.
    If a client is provided, an optional db_name can be passed; otherwise a default
    name will be used (suitable for tests with fake clients that ignore the name).
    """

    def __init__(self, db_or_client: AsyncIOMotorDatabase | AsyncIOMotorClient, db_name: Optional[str] = None):
        if hasattr(db_or_client, "get_collection"):
            # It's a database
            self.db: AsyncIOMotorDatabase = db_or_client  # type: ignore[assignment]
        elif hasattr(db_or_client, "get_database"):
            # It's a client
            self.db = db_or_client.get_database(db_name or "ai-chatbot-framework")  # type: ignore[attr-defined]
        else:
            raise TypeError("MemorySaverMongo requires an AsyncIOMotorDatabase or AsyncIOMotorClient instance")
        self.collection = self.db.get_collection("state")

    async def save(self, thread_id: Text, state: State):
        await self.collection.insert_one(state.to_dict())

    async def get(self, thread_id: Text) -> Optional[State]:
        result = await self.collection.find_one(
            {"thread_id": thread_id},
            {"_id": 0, "nlu": 0, "date": 0, "user_message": 0, "bot_message": 0},
            sort=[("$natural", -1)],
        )
        if result:
            return State.from_dict(result)
        return None

    async def get_all(self, thread_id: Text) -> List[State]:
        results = await self.collection.find(
            {"thread_id": thread_id}, sort=[("$natural", -1)]
        ).to_list()
        return [State.from_dict(result) for result in results]