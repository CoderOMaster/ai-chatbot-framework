from typing import AsyncIterator, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.bots.schemas import NLUConfiguration
from app.admin.bots.store import (
    ExportChunk,
    MongoBotRepository,
    _chunked,
)
from app.admin.entities.schemas import Entity, EntityValue as SchemaEntityValue
from app.admin.intents.schemas import Intent
from app.admin.entities.store import EntityRepository
from app.admin.intents.store import IntentRepository


def make_intent(name: str) -> Intent:
    """Builds a minimal valid intent for reuse in tests."""

    return Intent(
        name=name,
        intentId=f"{name}-id",
        speechResponse="ok",
        apiTrigger=False,
        userDefined=True,
        parameters=[],
        labeledSentences=[],
        trainingData=[],
    )


def make_entity(name: str) -> Entity:
    """Builds a minimal valid entity for reuse in tests."""

    return Entity(name=name, entity_values=[SchemaEntityValue(value="value", synonyms=["v1"])])


@pytest.fixture
def bot_document() -> Dict[str, object]:
    """Simple bot document used to satisfy repository requirements."""

    return {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "name": "reformal-bot",
        "nlu_config": {"pipeline_type": "ml"},
    }


@pytest.fixture
def collection(bot_document: Dict[str, object]) -> AsyncMock:
    """Mocked MongoDB collection used by :class:`MongoBotRepository`."""

    coll = AsyncMock(spec=AsyncIOMotorCollection)
    # Use side_effect to make the mock awaitable
    coll.find_one = AsyncMock(return_value=bot_document)
    coll.update_one = AsyncMock(return_value=None)
    return coll


@pytest.fixture
def intent_repository() -> AsyncMock:
    """Async mock representing the intent repository dependency."""

    return AsyncMock(spec=IntentRepository)


@pytest.fixture
def entity_repository() -> AsyncMock:
    """Async mock representing the entity repository dependency."""

    return AsyncMock(spec=EntityRepository)


@pytest.fixture
def repository(
    collection: AsyncMock,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> MongoBotRepository:
    """Re-usable MongoBotRepository instance with small batch size for chunking tests."""

    return MongoBotRepository(
        collection=collection,
        intent_repository=intent_repository,
        entity_repository=entity_repository,
        export_batch_size=2,
    )


def test_chunked_yields_expected_batches() -> None:
    """Ensure _chunked creates equally sized batches and emits a final partial chunk."""

    items = list(range(5))
    chunks = list(_chunked(items, 2))

    assert chunks == [[0, 1], [2, 3], [4]]


def test_chunked_rejects_non_positive_batch_size() -> None:
    """Chunk helper should guard against invalid batch sizes."""

    with pytest.raises(ValueError):
        list(_chunked([1, 2], 0))


@pytest.mark.asyncio
async def test_get_bot_returns_parsed_model(
    repository: MongoBotRepository,
) -> None:
    """get_bot should return a validated Bot model from the collection document."""

    bot = await repository.get_bot("reformal-bot")

    assert bot.name == "reformal-bot"
    assert isinstance(bot.nlu_config, NLUConfiguration)
    repository._collection.find_one.assert_awaited_once_with({"name": "reformal-bot"})


@pytest.mark.asyncio
async def test_get_nlu_config_returns_nested_configuration(
    repository: MongoBotRepository,
) -> None:
    """get_nlu_config should delegate to get_bot and return the configuration object."""

    nlu_config = await repository.get_nlu_config("reformal-bot")

    assert isinstance(nlu_config, NLUConfiguration)
    assert nlu_config.pipeline_type.name == "ML"


@pytest.mark.asyncio
async def test_update_nlu_config_persists_changes(
    repository: MongoBotRepository,
) -> None:
    """update_nlu_config should update the nlu_config sub-document in MongoDB."""

    new_config = {"pipeline_type": "zero_shot"}

    await repository.update_nlu_config("reformal-bot", new_config)

    repository._collection.update_one.assert_awaited_once_with(
        {"name": "reformal-bot"}, {"$set": {"nlu_config": new_config}}
    )


@pytest.mark.asyncio
async def test_stream_export_respects_batch_size_and_yields_chunks(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """stream_export should yield intent and entity chunks honoring the requested batch size."""

    intent_repository.list_intents = AsyncMock(return_value=[make_intent("a"), make_intent("b")])
    entity_repository.list_entities = AsyncMock(return_value=[make_entity("color"), make_entity("shape")])

    chunk_iter = repository.stream_export("reformal-bot", batch_size=1)
    chunks = [chunk async for chunk in chunk_iter]

    assert len(chunks) == 4
    assert chunks[0]["type"] == "intents"
    assert chunks[3]["type"] == "entities"
    assert all(len(chunk["items"]) == 1 for chunk in chunks)

    intent_repository.list_intents.assert_awaited_once()
    entity_repository.list_entities.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_export_uses_default_batch_size_when_not_provided(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """When no batch size is passed, stream_export should fall back to the repository default."""

    intents = [make_intent(str(i)) for i in range(3)]
    entities = [make_entity(str(i)) for i in range(2)]
    intent_repository.list_intents = AsyncMock(return_value=intents)
    entity_repository.list_entities = AsyncMock(return_value=entities)

    chunks = [chunk async for chunk in repository.stream_export("reformal-bot")]

    # With batch_size=2 (repository default):
    # - 3 intents -> 2 chunks (2 items, then 1 item)
    # - 2 entities -> 1 chunk (2 items)
    # Total: 3 chunks
    assert len(chunks) == 3
    assert all(len(chunk["items"]) <= repository._default_export_batch_size for chunk in chunks)


@pytest.mark.asyncio
async def test_import_from_stream_aggregates_data_and_counts(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """import_from_stream should combine streamed chunks and report created counts."""

    async def fake_stream() -> AsyncIterator[ExportChunk]:
        yield ExportChunk(type="intents", items=[{"name": "i1"}])
        yield ExportChunk(type="entities", items=[{"name": "e1"}])

    intent_repository.bulk_import_intents = AsyncMock(return_value=["i-1"])
    entity_repository.bulk_import_entities = AsyncMock(return_value=["e-1", "e-2"])

    result = await repository.import_from_stream("reformal-bot", fake_stream())

    intent_repository.bulk_import_intents.assert_awaited_once_with([{"name": "i1"}])
    entity_repository.bulk_import_entities.assert_awaited_once_with([{"name": "e1"}])
    assert result == {"num_intents_created": 1, "num_entities_created": 2}


@pytest.mark.asyncio
async def test_import_bot_streams_chunked_data_and_persists_counts(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """import_bot should leverage import_from_stream and honor the repository batch size."""

    data = {
        "intents": [{"name": f"intent-{i}"} for i in range(3)],
        "entities": [{"name": "color"}],
    }

    intent_repository.bulk_import_intents = AsyncMock(return_value=["i1", "i2"])
    entity_repository.bulk_import_entities = AsyncMock(return_value=[])

    with patch("app.admin.bots.store._chunked", wraps=_chunked) as chunked_patch:
        result = await repository.import_bot("reformal-bot", data)

    chunked_patch.assert_any_call(data["intents"], repository._default_export_batch_size)
    chunked_patch.assert_any_call(data["entities"], repository._default_export_batch_size)
    intent_repository.bulk_import_intents.assert_awaited_once()
    entity_repository.bulk_import_entities.assert_awaited_once()
    assert result == {"num_intents_created": 2, "num_entities_created": 0}


@pytest.mark.asyncio
async def test_export_bot_consolidates_streamed_chunks(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """export_bot should collect every chunk from stream_export into a single payload."""

    intent_repository.list_intents = AsyncMock(return_value=[make_intent("one")])
    entity_repository.list_entities = AsyncMock(return_value=[make_entity("shape")])

    payload = await repository.export_bot("reformal-bot")

    assert "intents" in payload and "entities" in payload
    assert len(payload["intents"]) == 1
    assert len(payload["entities"]) == 1


@pytest.mark.asyncio
async def test_import_from_stream_handles_unknown_chunk_types(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """Chunks with unexpected type values should fall back to the entities bucket."""

    async def fake_stream() -> AsyncIterator[ExportChunk]:
        yield ExportChunk(type="unknown", items=[{"name": "mystery"}])

    intent_repository.bulk_import_intents = AsyncMock(return_value=[])
    entity_repository.bulk_import_entities = AsyncMock(return_value=["m1"])

    await repository.import_from_stream("reformal-bot", fake_stream())

    intent_repository.bulk_import_intents.assert_awaited_once_with([])
    entity_repository.bulk_import_entities.assert_awaited_once_with([{"name": "mystery"}])


@pytest.mark.asyncio
async def test_import_bot_skips_missing_entity_data(
    repository: MongoBotRepository,
    intent_repository: AsyncMock,
    entity_repository: AsyncMock,
) -> None:
    """If no entity data is supplied, entity bulk import should still receive an empty list."""

    data = {"intents": [{"name": "only-intent"}]}
    intent_repository.bulk_import_intents = AsyncMock(return_value=[])
    entity_repository.bulk_import_entities = AsyncMock(return_value=[])

    await repository.import_bot("reformal-bot", data)

    entity_repository.bulk_import_entities.assert_awaited_once_with([])

    intent_repository.bulk_import_intents.assert_awaited_once_with(
        [{"name": "only-intent"}]
    )


__all__ = [
    "test_chunked_yields_expected_batches",
    "test_chunked_rejects_non_positive_batch_size",
    "test_get_bot_returns_parsed_model",
    "test_get_nlu_config_returns_nested_configuration",
    "test_update_nlu_config_persists_changes",
    "test_stream_export_respects_batch_size_and_yields_chunks",
    "test_stream_export_uses_default_batch_size_when_not_provided",
    "test_import_from_stream_aggregates_data_and_counts",
    "test_import_bot_streams_chunked_data_and_persists_counts",
    "test_export_bot_consolidates_streamed_chunks",
    "test_import_from_stream_handles_unknown_chunk_types",
    "test_import_bot_skips_missing_entity_data",
]