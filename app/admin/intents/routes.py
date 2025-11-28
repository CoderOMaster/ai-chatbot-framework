from fastapi import APIRouter, Depends

from app.admin.intents.schemas import Intent
from app.admin.intents.store import IntentRepository, MongoIntentRepository
from app.config import app_config
from app.database import create_collection_getter_from_config

router = APIRouter(prefix="/intents", tags=["intents"])

_collection_getter = create_collection_getter_from_config(app_config)


def get_intent_repository() -> IntentRepository:
    """Provide a Mongo-backed intent repository backed by the shared configuration."""

    collection = _collection_getter("intents")
    return MongoIntentRepository(collection)


async def create_intent_handler(
    repository: IntentRepository,
    intent: Intent,
) -> Intent:
    """Persist a new intent using the provided repository."""

    intent_payload = intent.model_dump(exclude={"id"})
    return await repository.add_intent(intent_payload)


async def list_intents_handler(repository: IntentRepository) -> list[Intent]:
    """Return every intent stored in the repository."""

    return await repository.list_intents()


async def read_intent_handler(
    repository: IntentRepository,
    intent_id: str,
) -> Intent:
    """Fetch a single intent by its identifier."""

    return await repository.get_intent(intent_id)


async def update_intent_handler(
    repository: IntentRepository,
    intent_id: str,
    intent: Intent,
) -> dict[str, str]:
    """Apply updates to the named intent."""

    intent_payload = intent.model_dump(exclude={"id"})
    await repository.edit_intent(intent_id, intent_payload)
    return {"status": "success"}


async def delete_intent_handler(
    repository: IntentRepository,
    intent_id: str,
) -> dict[str, str]:
    """Remove the intent with the given identifier."""

    await repository.delete_intent(intent_id)
    return {"status": "success"}


@router.post("/")
async def create_intent(
    intent: Intent,
    repository: IntentRepository = Depends(get_intent_repository),
) -> Intent:
    """Create a new intent."""

    return await create_intent_handler(repository, intent)


@router.get("/")
async def read_intents(
    repository: IntentRepository = Depends(get_intent_repository),
) -> list[Intent]:
    """List every intent."""

    return await list_intents_handler(repository)


@router.get("/{intent_id}")
async def read_intent(
    intent_id: str,
    repository: IntentRepository = Depends(get_intent_repository),
) -> Intent:
    """Retrieve a specific intent by ID."""

    return await read_intent_handler(repository, intent_id)


@router.put("/{intent_id}")
async def update_intent(
    intent_id: str,
    intent: Intent,
    repository: IntentRepository = Depends(get_intent_repository),
) -> dict[str, str]:
    """Update an intent."""

    return await update_intent_handler(repository, intent_id, intent)


@router.delete("/{intent_id}")
async def delete_intent(
    intent_id: str,
    repository: IntentRepository = Depends(get_intent_repository),
) -> dict[str, str]:
    """Delete an intent."""

    return await delete_intent_handler(repository, intent_id)