import asyncio
from typing import Any, Callable, Coroutine, Final, List, Optional, Text, TypeVar

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.errors import PyMongoError

from app.bot.memory import MemorySaver
from app.bot.memory.models import State
from app.config import app_config


_DEFAULT_COLLECTION_NAME: Final[Text] = "state"
_DEFAULT_OPERATION_TIMEOUT_SECONDS: Final[float] = 5.0
_STATE_PROJECTION: Final[dict[str, bool]] = {
    "_id": False,
    "nlu": False,
    "date": False,
    "user_message": False,
    "bot_message": False,
}

CollectionFactory = Callable[[AsyncIOMotorClient], AsyncIOMotorCollection]
T = TypeVar("T")


class MemorySaverMongoError(RuntimeError):
    """Raised when MongoDB operations fail within the MemorySaver implementation."""


class MemorySaverMongo(MemorySaver):
    """Memory persistence implementation backed by MongoDB collections."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        *,
        database_name: Optional[Text] = None,
        collection_name: Optional[Text] = None,
        collection_factory: Optional[CollectionFactory] = None,
        timeout_seconds: float = _DEFAULT_OPERATION_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._database_name = database_name or app_config.MONGODB_DATABASE
        self._collection_name = collection_name or _DEFAULT_COLLECTION_NAME
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._collection_factory = (
            collection_factory or self._default_collection_factory
        )
        self._collection = self._collection_factory(self._client)

    def _default_collection_factory(
        self, client: AsyncIOMotorClient
    ) -> AsyncIOMotorCollection:
        """Return the target Mongo collection using configured database and collection names."""

        return client.get_database(self._database_name).get_collection(
            self._collection_name
        )

    async def _execute(
        self,
        coroutine: Coroutine[Any, Any, T],
        operation_description: Text,
    ) -> T:
        """Execute a coroutine with a bounded timeout and wrap Mongo errors."""

        try:
            return await asyncio.wait_for(coroutine, self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise MemorySaverMongoError(
                f"{operation_description} timed out after {self._timeout_seconds:.1f} seconds"
            ) from exc
        except PyMongoError as exc:
            raise MemorySaverMongoError(
                f"{operation_description} failed: {exc}",
            ) from exc

    async def save(self, thread_id: Text, state: State) -> None:
        """Persist the provided state for the thread in MongoDB."""

        await self._execute(
            self._collection.insert_one(state.to_dict()),
            "persisting conversation state",
        )

    async def get(self, thread_id: Text) -> Optional[State]:
        """Return the latest stored state for the given thread identifier."""

        document = await self._execute(
            self._collection.find_one(
                {"thread_id": thread_id},
                _STATE_PROJECTION,
                sort=[("$natural", -1)],
            ),
            "fetching latest conversation state",
        )
        if document:
            return State.from_dict(document)
        return None

    async def get_all(self, thread_id: Text) -> List[State]:
        """Return the complete history of states for the requested thread."""

        documents = await self._execute(
            self._collection
            .find({"thread_id": thread_id}, sort=[("$natural", -1)])
            .to_list(length=None),
            "fetching full conversation history",
        )
        return [State.from_dict(result) for result in documents]