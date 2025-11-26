from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from app.admin.intents.schemas import Intent
from app.admin.intents.store import IntentRepository

router = APIRouter(prefix="/intents", tags=["intents"])


def _missing_repo_dependency() -> IntentRepository:
    """Default dependency that explains the repository must be provided by the application.

    Applications should override this dependency with a concrete provider that
    returns an implementation of IntentRepository (for example a MongoIntentRepository
    bound to a collection) via FastAPI's dependency injection system.
    """
    raise HTTPException(
        status_code=500,
        detail=(
            "IntentRepository dependency not configured. "
            "Provide a dependency that returns an IntentRepository implementation."
        ),
    )


# Pure handler functions (framework-agnostic) -------------------------------------------------
async def create_intent_handler(repo: IntentRepository, intent: Intent) -> Intent:
    """Create a new intent using the provided repository and return the persisted Intent.

    Args:
        repo: An implementation of IntentRepository used to persist the intent.
        intent: The Intent model to create.

    Returns:
        The created Intent as returned by the repository.
    """
    intent_dict: Dict[str, Any] = intent.model_dump(exclude={"id"})
    return await repo.add_intent(intent_dict)


async def read_intents_handler(repo: IntentRepository) -> List[Intent]:
    """Return a list of all stored intents."""
    return await repo.list_intents()


async def read_intent_handler(repo: IntentRepository, intent_id: str) -> Intent:
    """Return a single intent by ID."""
    return await repo.get_intent(intent_id)


async def update_intent_handler(repo: IntentRepository, intent_id: str, intent: Intent) -> Dict[str, str]:
    """Update an existing intent and return a simple status dict."""
    intent_dict: Dict[str, Any] = intent.model_dump(exclude={"id"})
    await repo.edit_intent(intent_id, intent_dict)
    return {"status": "success"}


async def delete_intent_handler(repo: IntentRepository, intent_id: str) -> Dict[str, str]:
    """Delete an intent and return a simple status dict."""
    await repo.delete_intent(intent_id)
    return {"status": "success"}


# FastAPI route wrappers (call the pure handlers) ----------------------------------------------
# Applications should override _missing_repo_dependency with a provider that returns
# a concrete IntentRepository implementation (or include this router with dependencies).


@router.post("/")
async def create_intent(intent: Intent, repo: IntentRepository = Depends(_missing_repo_dependency)):
    """FastAPI route wrapper for creating an intent."""
    return await create_intent_handler(repo, intent)


@router.get("/")
async def read_intents(repo: IntentRepository = Depends(_missing_repo_dependency)):
    """FastAPI route wrapper for listing intents."""
    return await read_intents_handler(repo)


@router.get("/{intent_id}")
async def read_intent(intent_id: str, repo: IntentRepository = Depends(_missing_repo_dependency)):
    """FastAPI route wrapper for retrieving a single intent."""
    return await read_intent_handler(repo, intent_id)


@router.put("/{intent_id}")
async def update_intent(intent_id: str, intent: Intent, repo: IntentRepository = Depends(_missing_repo_dependency)):
    """FastAPI route wrapper for updating an intent."""
    return await update_intent_handler(repo, intent_id, intent)


@router.delete("/{intent_id}")
async def delete_intent(intent_id: str, repo: IntentRepository = Depends(_missing_repo_dependency)):
    """FastAPI route wrapper for deleting an intent."""
    return await delete_intent_handler(repo, intent_id)