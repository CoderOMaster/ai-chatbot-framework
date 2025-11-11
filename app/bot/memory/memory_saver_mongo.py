from typing import Text, Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.bot.memory.models import State
from app.bot.memory import MemorySaver


class MemorySaverMongo(MemorySaver):
    """
    MemorySaverMongo implements the MemorySaver interface for MongoDB.
    Now depends on an injected AsyncIOMotorDatabase instance (adapter pattern).
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "state"):
        self.db = db
        self.collection = self.db.get_collection(collection_name)

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
        cursor = self.collection.find({"thread_id": thread_id}, sort=[("$natural", -1)])
        results = await cursor.to_list(length=None)
        return [State.from_dict(result) for result in results]