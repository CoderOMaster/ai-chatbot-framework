from typing import Text, Optional, List
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.bot.memory.models import State
from app.bot.memory import MemorySaver

logger = logging.getLogger(__name__)


class MemorySaverMongo(MemorySaver):
    """
    MemorySaverMongo implements the MemorySaver interface for MongoDB.

    This adapter expects an AsyncIOMotorDatabase instance (not a top-level client)
    so it can be easily injected and tested. It no longer creates or depends on a
    module-level client singleton.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = self.db.get_collection("state")

    async def save(self, thread_id: Text, state: State):
        try:
            await self.collection.insert_one(state.to_dict())
        except Exception as exc:  # keep broad catch to avoid leaking DB errors
            logger.exception("Failed to save state to MongoDB: %s", exc)
            raise

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
        results = await self.collection.find({"thread_id": thread_id}, sort=[("$natural", -1)]).to_list()
        return [State.from_dict(result) for result in results]