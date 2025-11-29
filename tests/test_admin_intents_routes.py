import pytest
from bson import ObjectId
from unittest.mock import AsyncMock

from app.admin.intents.routes import (
    create_intent_handler,
    delete_intent_handler,
    get_intent_repository,
    list_intents_handler,
    read_intent_handler,
    update_intent_handler,
)
from app.admin.intents.schemas import Intent
from app.admin.intents.store import IntentRepository


@pytest.fixture

def sample_intent() -> Intent:
    """Return a reusable intent instance for handler assertions."""
    return Intent(
        id=ObjectId(),
        name="greet",
        userDefined=True,
        intentId="greet_intent",
        apiTrigger=False,
        speechResponse="Hello",
        parameters=[],
        labeledSentences=[],
        trainingData=[],
    )


@pytest.fixture

def intent_repository_mock() -> AsyncMock:
    """Provide an AsyncMock that conforms to the IntentRepository protocol."""
    return AsyncMock(spec=IntentRepository)


@pytest.mark.asyncio
async def test_create_intent_handler_passes_payload_without_id(
    intent_repository_mock: AsyncMock, sample_intent: Intent
) -> None:
    """Ensure the handler omits the intent id when delegating to the repository."""
    intent_repository_mock.add_intent.return_value = sample_intent

    result = await create_intent_handler(intent_repository_mock, sample_intent)

    expected_payload = sample_intent.model_dump(exclude={"id"})
    intent_repository_mock.add_intent.assert_awaited_once_with(expected_payload)
    assert result is sample_intent


@pytest.mark.asyncio
async def test_create_intent_handler_propagates_repository_errors(
    intent_repository_mock: AsyncMock, sample_intent: Intent
) -> None:
    """Verify that repository failures bubble up through the intent handler."""
    intent_repository_mock.add_intent.side_effect = RuntimeError("insert failed")

    with pytest.raises(RuntimeError, match="insert failed"):
        await create_intent_handler(intent_repository_mock, sample_intent)


@pytest.mark.asyncio
async def test_list_intents_handler_returns_all_entries(
    intent_repository_mock: AsyncMock, sample_intent: Intent
) -> None:
    """Confirm that listing intents returns the repository result unchanged."""
    intent_repository_mock.list_intents.return_value = [sample_intent]

    result = await list_intents_handler(intent_repository_mock)

    intent_repository_mock.list_intents.assert_awaited_once()
    assert result == [sample_intent]


@pytest.mark.asyncio
async def test_read_intent_handler_fetches_by_identifier(
    intent_repository_mock: AsyncMock, sample_intent: Intent
) -> None:
    """Ensure a single intent is retrieved using the supplied id."""
    intent_repository_mock.get_intent.return_value = sample_intent

    result = await read_intent_handler(intent_repository_mock, "intent-id")

    intent_repository_mock.get_intent.assert_awaited_once_with("intent-id")
    assert result is sample_intent


@pytest.mark.asyncio
async def test_update_intent_handler_applies_updates_and_reports_success(
    intent_repository_mock: AsyncMock, sample_intent: Intent
) -> None:
    """Validate that intent updates omit the id and return a success payload."""
    result = await update_intent_handler(
        intent_repository_mock, "intent-id", sample_intent
    )

    expected_payload = sample_intent.model_dump(exclude={"id"})
    intent_repository_mock.edit_intent.assert_awaited_once_with("intent-id", expected_payload)
    assert result == {"status": "success"}


@pytest.mark.asyncio
async def test_update_intent_handler_propagates_edit_errors(
    intent_repository_mock: AsyncMock, sample_intent: Intent
) -> None:
    """Confirm that errors raised while editing an intent are not swallowed."""
    intent_repository_mock.edit_intent.side_effect = ValueError("failed to edit")

    with pytest.raises(ValueError, match="failed to edit"):
        await update_intent_handler(intent_repository_mock, "intent-id", sample_intent)


@pytest.mark.asyncio
async def test_delete_intent_handler_reports_success_after_removal(
    intent_repository_mock: AsyncMock
) -> None:
    """Assert that deleting an intent raises no errors and returns success."""
    result = await delete_intent_handler(intent_repository_mock, "intent-id")

    intent_repository_mock.delete_intent.assert_awaited_once_with("intent-id")
    assert result == {"status": "success"}


def test_get_intent_repository_wires_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that the shared collection getter is used when instantiating MongoIntentRepository."""
    dummy_collection = object()

    def dummy_collection_getter(name: str) -> object:  # type: ignore[return-value]
        assert name == "intents"
        return dummy_collection

    created_repository = object()

    def fake_mongo_repository(collection: object) -> object:  # type: ignore[return-value]
        assert collection is dummy_collection
        return created_repository

    monkeypatch.setattr(
        "app.admin.intents.routes._collection_getter",
        dummy_collection_getter,
    )
    monkeypatch.setattr(
        "app.admin.intents.routes.MongoIntentRepository",
        fake_mongo_repository,
    )

    result = get_intent_repository()

    assert result is created_repository