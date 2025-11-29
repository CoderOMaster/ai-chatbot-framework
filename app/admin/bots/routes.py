from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.admin.bots.schemas import NLUConfiguration
from app.admin.bots.store import BotRepository, MongoBotRepository
from app.admin.entities.store import MongoEntityRepository
from app.admin.intents.store import MongoIntentRepository
from app.config import app_config
from app.database import create_collection_getter_from_config

router = APIRouter(prefix="/bots", tags=["bots"])

_collection_getter = create_collection_getter_from_config(app_config)


class BotConfigUpdateRequest(BaseModel):
    """Payload for updating a bot's NLU configuration."""

    config: NLUConfiguration


class BotConfigResponse(BaseModel):
    """DTO describing the persisted NLU configuration for a bot."""

    config: NLUConfiguration


class BotConfigUpdateResponse(BaseModel):
    """Acknowledgement for bot configuration updates."""

    message: str


class BotExportPayload(BaseModel):
    """Shape of the exported intents and entities for a bot."""

    intents: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)


class BotExportResponse(BaseModel):
    """DTO returned when exporting a bot."""

    bot_name: str
    payload: BotExportPayload


class BotImportRequest(BaseModel):
    """Payload accepted when importing bot data."""

    payload: BotExportPayload


class BotImportResponse(BaseModel):
    """Outcome from importing bot data."""

    num_intents_created: int
    num_entities_created: int


def get_bot_repository() -> BotRepository:
    """Return a Mongo-backed bot repository wired with intent and entity stores."""

    bot_collection = _collection_getter("bots")
    intent_collection = _collection_getter("intents")
    entity_collection = _collection_getter("entities")
    intent_repository = MongoIntentRepository(intent_collection)
    entity_repository = MongoEntityRepository(entity_collection)
    return MongoBotRepository(bot_collection, intent_repository, entity_repository)


async def set_config_handler(
    repository: BotRepository,
    name: str,
    request: BotConfigUpdateRequest,
) -> BotConfigUpdateResponse:
    """Persist the supplied config for the requested bot."""

    await repository.update_nlu_config(name, request.config.model_dump())
    return BotConfigUpdateResponse(message="Config updated successfully")


async def get_config_handler(
    repository: BotRepository,
    name: str,
) -> BotConfigResponse:
    """Retrieve the configured NLU settings for the bot."""

    config = await repository.get_nlu_config(name)
    return BotConfigResponse(config=config)


async def export_bot_handler(
    repository: BotRepository,
    name: str,
) -> BotExportResponse:
    """Gather the intents and entities for the named bot."""

    payload = await repository.export_bot(name)
    export_payload = BotExportPayload(
        intents=payload.get("intents", []),
        entities=payload.get("entities", []),
    )
    return BotExportResponse(bot_name=name, payload=export_payload)


async def import_bot_handler(
    repository: BotRepository,
    name: str,
    request: BotImportRequest,
) -> BotImportResponse:
    """Import the intents and entities payload for the requested bot."""

    result = await repository.import_bot(name, request.payload.model_dump())
    return BotImportResponse(**result)


@router.put("/{name}/config")
async def set_config(
    name: str,
    request: BotConfigUpdateRequest,
    repository: BotRepository = Depends(get_bot_repository),
) -> BotConfigUpdateResponse:
    """Update bot config"""

    return await set_config_handler(repository, name, request)


@router.get("/{name}/config")
async def get_config(
    name: str,
    repository: BotRepository = Depends(get_bot_repository),
) -> BotConfigResponse:
    """Get bot config"""

    return await get_config_handler(repository, name)


@router.get("/{name}/export")
async def export_bot(
    name: str,
    repository: BotRepository = Depends(get_bot_repository),
) -> BotExportResponse:
    """Export all intents and entities for the bot as JSON."""

    return await export_bot_handler(repository, name)


@router.post("/{name}/import")
async def import_bot(
    name: str,
    request: BotImportRequest,
    repository: BotRepository = Depends(get_bot_repository),
) -> BotImportResponse:
    """Import intents and entities from a JSON payload for the bot."""

    return await import_bot_handler(repository, name, request)