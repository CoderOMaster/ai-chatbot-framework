from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Text

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
)

from app.bot.memory.models import State
from app.bot.memory import MemorySaver
from app.config import get_app_config


logger = logging.getLogger(__name__)


class MemorySaverMongo(MemorySaver):
    """
    Mongo-backed implementation of MemorySaver.

    This class expects an already constructed AsyncIOMotorClient to be
    injected. Database and collection names may be provided explicitly or
    resolved from the application config; a per-operation timeout (seconds)
    can also be supplied (defaults to 5s if not configured).

    Important: Motor driver exceptions are caught and logged. On failure the
    methods return safe defaults (None or empty list) rather than letting
    driver exceptions propagate to higher-level code.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        db_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """
        Initialize the saver.

        Args:
            client: An injected AsyncIOMotorClient instance (do not construct
                the client inside this class; construct and manage lifecycle
                in application wiring code).
            db_name: Optional override for the Mongo database name.
            collection_name: Optional override for the collection name.
            timeout: Per-operation timeout in seconds. If omitted the value is
                taken from app config (MONGO_OPERATION_TIMEOUT /
                mongo_operation_timeout) or defaults to 5.0 seconds.
        """
        self.client = client

        config = get_app_config()

        # Resolve database/collection names from explicit args, app config
        # or sensible defaults.
        self.db_name = (
            db_name
            or getattr(config, "MONGO_DB_NAME", None)
            or getattr(config, "mongo_db_name", None)
            or "chatbot"
        )
        self.collection_name = (
            collection_name
            or getattr(config, "MONGO_COLLECTION_NAME", None)
            or getattr(config, "mongo_collection_name", None)
            or "state"
        )

        # Resolve timeout value (seconds)
        self.timeout = (
            timeout
            or getattr(config, "MONGO_OPERATION_TIMEOUT", None)
            or getattr(config, "mongo_operation_timeout", None)
            or 5.0
        )

        self.db = client.get_database(self.db_name)
        self.collection: AsyncIOMotorCollection = self.db.get_collection(
            self.collection_name
        )

    async def save(self, thread_id: Text, state: State) -> None:
        """Persist a State instance to MongoDB.

        Errors and timeouts are logged and swallowed to avoid leaking Motor
        internals to callers.
        """
        try:
            await asyncio.wait_for(
                self.collection.insert_one(state.to_dict()), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.exception("Timeout while saving state for thread %s", thread_id)
        except Exception:
            logger.exception("Failed to save state for thread %s", thread_id)

    async def get(self, thread_id: Text) -> Optional[State]:
        """Return the latest stored State for thread_id, or None.

        The projection intentionally excludes heavier fields to return a
        lightweight state preview.
        """
        try:
            result = await asyncio.wait_for(
                self.collection.find_one(
                    {"thread_id": thread_id},
                    {"_id": 0, "nlu": 0, "date": 0, "user_message": 0, "bot_message": 0},
                    sort=[("$natural", -1)],
                ),
                timeout=self.timeout,
            )
            if result:
                return State.from_dict(result)
            return None
        except asyncio.TimeoutError:
            logger.exception("Timeout while fetching latest state for thread %s", thread_id)
            return None
        except Exception:
            logger.exception("Failed to fetch latest state for thread %s", thread_id)
            return None

    async def get_all(self, thread_id: Text) -> List[State]:
        """Return all stored State entries for thread_id (as a list).

        On errors an empty list is returned. The method currently limits the
        number of results fetched in one call to avoid unbounded memory use.
        """
        try:
            cursor = self.collection.find({"thread_id": thread_id}, sort=[("$natural", -1)])
            # Protect against unbounded result sizes by applying a reasonable
            # max fetch. If callers need more, change the implementation to
            # accept a limit/offset or a streaming API.
            results = await asyncio.wait_for(cursor.to_list(length=1000), timeout=self.timeout)
            return [State.from_dict(result) for result in results]
        except asyncio.TimeoutError:
            logger.exception("Timeout while fetching states for thread %s", thread_id)
            return []
        except Exception:
            logger.exception("Failed to fetch states for thread %s", thread_id)
            return []