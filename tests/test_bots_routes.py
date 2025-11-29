import pytest
from unittest.mock import AsyncMock

from app.admin.bots.routes import (
    BotConfigUpdateRequest,
    BotExportPayload,
    BotImportRequest,
    BotConfigResponse,
    BotConfigUpdateResponse,
    BotExportResponse,
    BotImportResponse,
    get_bot_repository,
    set_config_handler,
    get_config_handler,
    export_bot_handler,
    import_bot_handler,
    BotRepository,
)
from app.admin.bots.schemas import NLUConfiguration, PipelineType


@pytest.fixture
def bot_repository_mock() -> AsyncMock:
    """Provide an AsyncMock that simulates the BotRepository interface."""

    return AsyncMock(spec=BotRepository)


@pytest.mark.asyncio
async def test_set_config_handler_updates_repository_and_returns_ack(
    bot_repository_mock: AsyncMock,
) -> None:
    """set_config_handler should persist the provided NLU config and return a success message."""

    request = BotConfigUpdateRequest(config=NLUConfiguration())

    response = await set_config_handler(bot_repository_mock, "test-bot", request)

    bot_repository_mock.update_nlu_config.assert_awaited_once_with(
        "test-bot", request.config.model_dump()
    )
    assert isinstance(response, BotConfigUpdateResponse)
    assert response.message == "Config updated successfully"


@pytest.mark.asyncio
async def test_get_config_handler_returns_config_from_repository(
    bot_repository_mock: AsyncMock,
) -> None:
    """get_config_handler should return the configuration fetched from the repository."""

    expected_config = NLUConfiguration(pipeline_type=PipelineType.ZERO_SHOT)
    bot_repository_mock.get_nlu_config.return_value = expected_config

    response = await get_config_handler(bot_repository_mock, "test-bot")

    bot_repository_mock.get_nlu_config.assert_awaited_once_with("test-bot")
    assert isinstance(response, BotConfigResponse)
    assert response.config == expected_config


@pytest.mark.asyncio
async def test_export_bot_handler_returns_payload_with_defaults(
    bot_repository_mock: AsyncMock,
) -> None:
    """export_bot_handler should default to empty lists when repository payload omits keys."""

    bot_repository_mock.export_bot.return_value = {}

    response = await export_bot_handler(bot_repository_mock, "test-bot")

    bot_repository_mock.export_bot.assert_awaited_once_with("test-bot")
    assert isinstance(response, BotExportResponse)
    assert response.bot_name == "test-bot"
    assert response.payload.intents == []
    assert response.payload.entities == []


@pytest.mark.asyncio
async def test_export_bot_handler_includes_intents_and_entities(
    bot_repository_mock: AsyncMock,
) -> None:
    """export_bot_handler should forward repository-provided intents and entities."""

    data = {"intents": [{"name": "Foo"}], "entities": [{"name": "Bar"}]}
    bot_repository_mock.export_bot.return_value = data

    response = await export_bot_handler(bot_repository_mock, "test-bot")

    assert response.payload.intents == data["intents"]
    assert response.payload.entities == data["entities"]


@pytest.mark.asyncio
async def test_import_bot_handler_calls_repository_with_payload(
    bot_repository_mock: AsyncMock,
) -> None:
    """import_bot_handler should forward the payload to the repository and surface counts."""

    payload = BotExportPayload(intents=[{"name": "Foo"}], entities=[{"name": "Bar"}])
    request = BotImportRequest(payload=payload)
    bot_repository_mock.import_bot.return_value = {
        "num_intents_created": 2,
        "num_entities_created": 1,
    }

    response = await import_bot_handler(bot_repository_mock, "test-bot", request)

    bot_repository_mock.import_bot.assert_awaited_once_with(
        "test-bot", request.payload.model_dump()
    )
    assert isinstance(response, BotImportResponse)
    assert response.num_intents_created == 2
    assert response.num_entities_created == 1


def test_bot_export_payload_defaults_empty_lists() -> None:
    """BotExportPayload should initialise with empty intent and entity collections."""

    payload = BotExportPayload()

    assert payload.intents == []
    assert payload.entities == []


def test_get_bot_repository_wires_underlying_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_bot_repository should construct Mongo repositories using the configured collections."""

    created_collections: list[str] = []

    def fake_collection_getter(name: str) -> str:
        created_collections.append(name)
        return f"collection::{name}"

    class DummyIntentRepo:
        def __init__(self, collection: str) -> None:
            self.collection = collection

    class DummyEntityRepo:
        def __init__(self, collection: str) -> None:
            self.collection = collection

    class DummyBotRepo:
        def __init__(
            self,
            bot_collection: str,
            intent_repository: DummyIntentRepo,
            entity_repository: DummyEntityRepo,
        ) -> None:
            self.bot_collection = bot_collection
            self.intent_repository = intent_repository
            self.entity_repository = entity_repository

    monkeypatch.setattr("app.admin.bots.routes._collection_getter", fake_collection_getter)
    monkeypatch.setattr("app.admin.bots.routes.MongoIntentRepository", DummyIntentRepo)
    monkeypatch.setattr("app.admin.bots.routes.MongoEntityRepository", DummyEntityRepo)
    monkeypatch.setattr("app.admin.bots.routes.MongoBotRepository", DummyBotRepo)

    repository = get_bot_repository()

    assert isinstance(repository, DummyBotRepo)
    assert repository.bot_collection == "collection::bots"
    assert repository.intent_repository.collection == "collection::intents"
    assert repository.entity_repository.collection == "collection::entities"
    assert created_collections == ["bots", "intents", "entities"]


@pytest.mark.asyncio
async def test_set_config_handler_with_custom_pipeline_type(
    bot_repository_mock: AsyncMock,
) -> None:
    """set_config_handler should handle non-default pipeline types correctly."""

    config = NLUConfiguration(pipeline_type=PipelineType.ZERO_SHOT)
    request = BotConfigUpdateRequest(config=config)

    await set_config_handler(bot_repository_mock, "test-bot", request)

    bot_repository_mock.update_nlu_config.assert_awaited_once_with(
        "test-bot", request.config.model_dump()
    )