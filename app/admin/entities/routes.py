from fastapi import APIRouter, Depends

from app.admin.entities.schemas import Entity
from app.admin.entities.store import EntityRepository, MongoEntityRepository
from app.config import app_config
from app.database import create_collection_getter_from_config

router = APIRouter(prefix="/entities", tags=["entities"])

_collection_getter = create_collection_getter_from_config(app_config)


def get_entity_repository() -> EntityRepository:
    """Return a Mongo-backed entity repository using the shared configuration."""

    collection = _collection_getter("entities")
    return MongoEntityRepository(collection)


async def create_entity_handler(
    repository: EntityRepository,
    entity: Entity,
) -> Entity:
    """Persist a new entity and return the stored document."""

    entity_payload = entity.model_dump(exclude={"id"})
    return await repository.add_entity(entity_payload)


async def list_entities_handler(repository: EntityRepository) -> list[Entity]:
    """Return every entity stored in the repository."""

    return await repository.list_entities()


async def read_entity_handler(
    repository: EntityRepository,
    entity_id: str,
) -> Entity:
    """Fetch a single entity by its identifier."""

    return await repository.get_entity(entity_id)


async def update_entity_handler(
    repository: EntityRepository,
    entity_id: str,
    entity: Entity,
) -> dict[str, str]:
    """Update an existing entity and report success."""

    entity_payload = entity.model_dump(exclude={"id"})
    await repository.edit_entity(entity_id, entity_payload)
    return {"status": "success"}


async def delete_entity_handler(
    repository: EntityRepository,
    entity_id: str,
) -> dict[str, str]:
    """Delete an entity and return the resulting status."""

    await repository.delete_entity(entity_id)
    return {"status": "success"}


@router.post("/")
async def create_entity(
    entity: Entity,
    repository: EntityRepository = Depends(get_entity_repository),
) -> Entity:
    """Create a new entity document."""

    return await create_entity_handler(repository, entity)


@router.get("/")
async def read_entities(
    repository: EntityRepository = Depends(get_entity_repository),
) -> list[Entity]:
    """List all entities."""

    return await list_entities_handler(repository)


@router.get("/{entity_id}")
async def read_entity(
    entity_id: str,
    repository: EntityRepository = Depends(get_entity_repository),
) -> Entity:
    """Retrieve an entity by its ID."""

    return await read_entity_handler(repository, entity_id)


@router.put("/{entity_id}")
async def update_entity(
    entity_id: str,
    entity: Entity,
    repository: EntityRepository = Depends(get_entity_repository),
) -> dict[str, str]:
    """Apply updates to an entity."""

    return await update_entity_handler(repository, entity_id, entity)


@router.delete("/{entity_id}")
async def delete_entity(
    entity_id: str,
    repository: EntityRepository = Depends(get_entity_repository),
) -> dict[str, str]:
    """Delete an entity by identifier."""

    return await delete_entity_handler(repository, entity_id)