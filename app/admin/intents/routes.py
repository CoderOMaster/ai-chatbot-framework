from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.admin.intents.schemas import Intent, to_object_id
from app.admin.intents.store import IntentRepository

router = APIRouter(prefix="/intents", tags=["intents"])


def get_intent_repository(request: Request) -> IntentRepository:
    """Dependency to retrieve the IntentRepository from the application state.

    The application is expected to attach an IntentRepository instance to
    request.app.state.intent_repo during startup. If it's missing a 500
    HTTPException is raised to indicate misconfiguration.
    """
    repo = getattr(request.app.state, "intent_repo", None)
    if repo is None:
        raise HTTPException(status_code=500, detail="Intent repository not configured")
    return repo


def validate_object_id(intent_id: str) -> str:
    """Dependency that validates intent_id is a valid BSON ObjectId string.

    Returns the original intent_id when valid. Raises HTTPException(404)
    for invalid IDs so handlers don't need to re-check syntax.
    """
    try:
        # to_object_id will raise on invalid values
        to_object_id(intent_id)
        return intent_id
    except Exception:
        raise HTTPException(status_code=404, detail="Intent not found")


def _dto_to_response(intent_dto: Optional[dict]) -> Optional[dict]:
    """Convert a repository DTO into a controlled response dict using the
    Intent schema for validation and field selection.

    The repository returns DTOs with an "id" string field; the Intent model
    expects the internal alias "_id" to be a BSON ObjectId, so we convert
    back before validation and then dump the model to a plain dict.
    """
    if intent_dto is None:
        return None

    data = intent_dto.copy()
    if "id" in data and data["id"] is not None:
        # Convert string id back to ObjectId for Pydantic validation
        data["_id"] = to_object_id(data.pop("id"))

    intent_model = Intent.model_validate(data)
    # model_dump returns a plain dict using field names (not aliases)
    return intent_model.model_dump()


@router.post("/", status_code=201)
async def create_intent(intent: Intent, repo: IntentRepository = Depends(get_intent_repository)):
    """Create a new intent.

    The incoming Intent is validated by Pydantic. We exclude any provided id
    and persist the remaining fields via the injected repository.
    """
    intent_dict = intent.model_dump(exclude={"id"})
    created = await repo.add_intent(intent_dict)
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to create intent")
    return _dto_to_response(created)


@router.get("/")
async def read_intents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    repo: IntentRepository = Depends(get_intent_repository),
) -> List[dict]:
    """Return a paginated list of intents.

    Pagination is performed at the API layer; repositories may be updated to
    support server-side pagination later.
    """
    intents = await repo.list_intents()
    # Apply pagination at the API layer to avoid returning very large payloads
    paginated = intents[skip : skip + limit]
    return [ _dto_to_response(i) for i in paginated ]


@router.get("/{intent_id}")
async def read_intent(
    intent_id: str = Depends(validate_object_id),
    repo: IntentRepository = Depends(get_intent_repository),
):
    """Get a specific intent by ID. Returns 404 when not found."""
    intent = await repo.get_intent(intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Intent not found")
    return _dto_to_response(intent)


@router.put("/{intent_id}")
async def update_intent(
    intent_id: str = Depends(validate_object_id),
    intent: Intent = Depends(),
    repo: IntentRepository = Depends(get_intent_repository),
):
    """Update an intent. Returns 404 when the target intent does not exist."""
    # model_dump to plain dict and exclude id if supplied
    intent_dict = intent.model_dump(exclude={"id"})
    await repo.edit_intent(intent_id, intent_dict)

    # Ensure the document exists after update
    updated = await repo.get_intent(intent_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Intent not found")
    return {"status": "success"}


@router.delete("/{intent_id}")
async def delete_intent(
    intent_id: str = Depends(validate_object_id),
    repo: IntentRepository = Depends(get_intent_repository),
):
    """Delete an intent. Returns 404 when the intent does not exist."""
    # Check existence first so we can return a 404 rather than a silent success
    existing = await repo.get_intent(intent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Intent not found")

    await repo.delete_intent(intent_id)
    return {"status": "success"}