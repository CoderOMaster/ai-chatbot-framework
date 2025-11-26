from typing import List

from fastapi import APIRouter, Depends

from app.admin.entities.store import EntityRepository, get_default_repository
from app.admin.entities.schemas import Entity

router = APIRouter(prefix="/entities", tags=["entities"])


@router.post("/", response_model=dict)
async def create_entity(
    entity: Entity, repository: EntityRepository = Depends(get_default_repository)
) -> dict:
    """Create a new entity using an injected EntityRepository.

    The repository is provided via FastAPI dependency injection by default
    but can be passed explicitly by callers (e.g. a Lambda adapter).
    """
    entity_dict = entity.model_dump(exclude={"id"})
    created = await repository.add_entity(entity_dict)
    return created.model_dump()


@router.get("/", response_model=List[dict])
async def read_entities(repository: EntityRepository = Depends(get_default_repository)) -> List[dict]:
    """Return all entities as plain dicts."""
    entities = await repository.list_entities()
    return [e.model_dump() for e in entities]


@router.get("/{entity_id}")
async def read_entity(entity_id: str, repository: EntityRepository = Depends(get_default_repository)) -> dict:
    """Get a specific entity by ID and return it as a dict."""
    entity = await repository.get_entity(entity_id)
    return entity.model_dump()


@router.put("/{entity_id}")
async def update_entity(entity_id: str, entity: Entity, repository: EntityRepository = Depends(get_default_repository)) -> dict:
    """Update an entity using the injected repository."""
    entity_dict = entity.model_dump(exclude={"id"})
    await repository.edit_entity(entity_id, entity_dict)
    return {"status": "success"}


@router.delete("/{entity_id}")
async def delete_entity(entity_id: str, repository: EntityRepository = Depends(get_default_repository)) -> dict:
    """Delete an entity using the injected repository."""
    await repository.delete_entity(entity_id)
    return {"status": "success"}