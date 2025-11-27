from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.admin.entities import store
from app.admin.entities.schemas import Entity

router = APIRouter(prefix="/entities", tags=["entities"])  # keep same prefix for compatibility


class EntityRepository:
    """Repository abstraction placed in front of the legacy store module.

    This small wrapper allows callers to obtain a repository via dependency
    injection while keeping the existing store implementation as the default
    backend. Tests can replace the dependency with a mock implementation.
    """

    async def add_entity(self, entity_data: Dict[str, Any]) -> Dict[str, Any]:
        return await store.add_entity(entity_data)

    async def list_entities(self) -> List[Dict[str, Any]]:
        return await store.list_entities()

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await store.get_entity(entity_id)

    async def edit_entity(self, entity_id: str, entity_data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
        return await store.edit_entity(entity_id, entity_data, expected_version=expected_version)

    async def delete_entity(self, entity_id: str) -> None:
        return await store.delete_entity(entity_id)


def get_repository() -> EntityRepository:
    """Dependency provider that returns the default EntityRepository.

    Tests can override this dependency to provide a different backend.
    """

    return EntityRepository()


def _entity_dict_to_model(d: Dict[str, Any]) -> Entity:
    """Convert a plain dict produced by the store into an Entity model.

    The store uses the database alias `_id` which Pydantic understands through
    the schema configuration; directly validate the dict into the Entity model.
    """

    # Pydantic v2 model validation entrypoint
    return Entity.model_validate(d)


def _format_etag(version: Optional[int]) -> Optional[str]:
    if version is None:
        return None
    return str(version)


def _parse_if_match_header(if_match: Optional[str]) -> Optional[int]:
    """Parse the If-Match header and return an integer version or raise HTTPException

    Accepts plain integers or quoted values and strips weak validators like W/.
    """

    if not if_match:
        return None

    val = if_match.strip()
    if val.startswith("W/"):
        val = val[2:]

    # strip surrounding quotes if present
    val = val.strip('"')
    try:
        return int(val)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid If-Match header")


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=Entity)
async def create_entity(entity: Entity, response: Response, repo: EntityRepository = Depends(get_repository)):  # type: ignore
    """Create a new entity.

    Returns the created Entity instance and sets an ETag header containing
    the optimistic concurrency version returned by the store.
    """
    entity_dict = entity.model_dump(exclude={"id"})
    created = await repo.add_entity(entity_dict)
    model = _entity_dict_to_model(created)

    # attach ETag header for optimistic concurrency
    etag = _format_etag(created.get("_version"))
    if etag:
        response.headers["ETag"] = etag

    return model


@router.get("/", response_model=List[Entity])
async def read_entities(
    response: Response,
    name: Optional[str] = Query(None, min_length=1, max_length=100),
    limit: int = Query(100, ge=1, le=1000),
    repo: EntityRepository = Depends(get_repository),
):
    """Get all entities, with optional simple filtering and sanitization of query params.

    The endpoint performs in-memory filtering when a `name` filter is provided to
    avoid changing the underlying store API.
    """
    raw = await repo.list_entities()

    # basic sanitization / filtering performed in Python to keep store API stable
    if name:
        filtered = [r for r in raw if r.get("name") == name]
    else:
        filtered = raw

    # enforce limit to avoid accidentally returning extremely large lists
    limited = filtered[:limit]

    entities = [_entity_dict_to_model(r) for r in limited]
    return entities


@router.get("/{entity_id}", response_model=Entity)
async def read_entity(entity_id: str, response: Response, repo: EntityRepository = Depends(get_repository)):
    """Get a specific entity by ID and include an ETag header with its version."""
    entity = await repo.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    model = _entity_dict_to_model(entity)
    etag = _format_etag(entity.get("_version"))
    if etag:
        response.headers["ETag"] = etag

    return model


@router.put("/{entity_id}")
async def update_entity(
    entity_id: str,
    entity: Entity,
    response: Response,
    if_match: Optional[str] = Header(None),
    repo: EntityRepository = Depends(get_repository),
):
    """Update an entity using optimistic concurrency when If-Match is provided.

    If the If-Match header is present it will be interpreted as the expected
    integer `_version`. On success the endpoint returns HTTP 204 No Content
    and sets a new ETag header reflecting the updated version.
    """
    expected_version = _parse_if_match_header(if_match)

    entity_dict = entity.model_dump(exclude={"id"})

    try:
        await repo.edit_entity(entity_id, entity_dict, expected_version=expected_version)
    except RuntimeError:
        # Map optimistic concurrency failures to 409 Conflict
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict or entity not found")

    # fetch updated entity to obtain new version for ETag
    updated = await repo.get_entity(entity_id)
    if updated is None:
        # If the entity vanished between update and fetch, report not found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    etag = _format_etag(updated.get("_version"))
    if etag:
        response.headers["ETag"] = etag

    # Return 204 No Content on successful update
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=response.headers)


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(entity_id: str, repo: EntityRepository = Depends(get_repository)):
    """Delete an entity and return HTTP 204 No Content on success."""
    await repo.delete_entity(entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)