from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
    Protocol,
    TypedDict,
    TypeVar,
)

from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.bots.schemas import Bot, NLUConfiguration
from app.admin.entities.store import EntityRepository
from app.admin.intents.store import IntentRepository


ChunkType = Literal["entities", "intents"]


class ExportChunk(TypedDict):
    """Represents a single portion of exportable intent or entity data."""

    type: ChunkType
    items: List[Dict[str, Any]]


_DEFAULT_EXPORT_BATCH_SIZE = 100
_T = TypeVar("_T")


def _chunked(iterable: Iterable[_T], chunk_size: int) -> Iterator[List[_T]]:
    """Yield successive chunks of ``chunk_size`` from ``iterable``."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    chunk: List[_T] = []
    for element in iterable:
        chunk.append(element)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class BotRepository(Protocol):
    """Protocol defining persistence surface for bot configuration."""

    async def get_bot(self, name: str) -> Bot:
        """Return the bot document for the requested name."""

    async def get_nlu_config(self, name: str) -> NLUConfiguration:
        """Fetch the Natural Language Understanding configuration for the bot."""

    async def update_nlu_config(self, name: str, nlu_config: Dict[str, Any]) -> None:
        """Override the stored NLU configuration with the supplied payload."""

    async def stream_export(
        self, name: str, batch_size: int | None = None
    ) -> AsyncIterator[ExportChunk]:
        """Yield intent and entity data in chunks for export streaming."""

    async def import_from_stream(
        self, name: str, data_stream: AsyncIterable[ExportChunk]
    ) -> Dict[str, int]:
        """Consume a stream of export chunks and materialize them back into the store."""

    async def export_bot(self, name: str) -> Dict[str, List[Dict[str, Any]]]:
        """Return a full package of intents and entities for the bot."""

    async def import_bot(
        self, name: str, data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, int]:
        """Import intents and entities from a raw payload."""


class MongoBotRepository(BotRepository):
    """MongoDB-backed implementation of :class:`BotRepository`."""

    def __init__(
        self,
        collection: AsyncIOMotorCollection,
        intent_repository: IntentRepository,
        entity_repository: EntityRepository,
        *,
        export_batch_size: int = _DEFAULT_EXPORT_BATCH_SIZE,
    ) -> None:
        self._collection = collection
        self._intent_repository = intent_repository
        self._entity_repository = entity_repository
        self._default_export_batch_size = export_batch_size

    async def get_bot(self, name: str) -> Bot:
        document = await self._collection.find_one({"name": name})
        return Bot.model_validate(document)

    async def get_nlu_config(self, name: str) -> NLUConfiguration:
        bot = await self.get_bot(name)
        return bot.nlu_config

    async def update_nlu_config(self, name: str, nlu_config: Dict[str, Any]) -> None:
        await self._collection.update_one(
            {"name": name}, {"$set": {"nlu_config": nlu_config}}
        )

    async def stream_export(
        self, name: str, batch_size: int | None = None
    ) -> AsyncIterator[ExportChunk]:
        _ = await self.get_bot(name)
        actual_batch_size = (
            batch_size if batch_size is not None else self._default_export_batch_size
        )
        intents = await self._intent_repository.list_intents()
        intent_payloads = [
            intent.model_dump(
                exclude={"id": True, "parameters": {"__all__": {"id"}}}
            )
            for intent in intents
        ]
        for chunk in _chunked(intent_payloads, actual_batch_size):
            yield ExportChunk(type="intents", items=chunk)

        entities = await self._entity_repository.list_entities()
        entity_payloads = [entity.model_dump(exclude={"id"}) for entity in entities]
        for chunk in _chunked(entity_payloads, actual_batch_size):
            yield ExportChunk(type="entities", items=chunk)

    async def import_from_stream(
        self, name: str, data_stream: AsyncIterable[ExportChunk]
    ) -> Dict[str, int]:
        _ = await self.get_bot(name)
        intents: List[Dict[str, Any]] = []
        entities: List[Dict[str, Any]] = []
        async for chunk in data_stream:
            target = intents if chunk["type"] == "intents" else entities
            target.extend(chunk["items"])

        created_intents = await self._intent_repository.bulk_import_intents(intents)
        created_entities = await self._entity_repository.bulk_import_entities(entities)

        return {
            "num_intents_created": len(created_intents),
            "num_entities_created": len(created_entities),
        }

    async def export_bot(self, name: str) -> Dict[str, List[Dict[str, Any]]]:
        payload: Dict[str, List[Dict[str, Any]]] = {"intents": [], "entities": []}
        async for chunk in self.stream_export(name=name):
            payload[chunk["type"]].extend(chunk["items"])
        return payload

    async def import_bot(
        self, name: str, data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, int]:
        async def _stream_from_dict() -> AsyncIterator[ExportChunk]:
            for chunk_type in ("intents", "entities"):
                items = data.get(chunk_type)
                if not items:
                    continue
                for batch in _chunked(items, self._default_export_batch_size):
                    yield ExportChunk(type=chunk_type, items=batch)

        return await self.import_from_stream(name=name, data_stream=_stream_from_dict())


__all__ = [
    "BotRepository",
    "MongoBotRepository",
    "ExportChunk",
]