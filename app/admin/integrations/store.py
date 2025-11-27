from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

# Avoid importing a global database at import time for multi-tenant support.
# We will attempt to use an existing `database` symbol for backward compatibility
# but prefer an explicit `db` parameter in API functions.
try:
    from app.database import database as _global_database  # type: ignore
except Exception:  # pragma: no cover - optional compatibility import
    _global_database = None

from app.admin.integrations.schemas import (
    Integration,
    IntegrationUpdate,
    IntegrationCreate,
)

DEFAULT_COLLECTION_NAME = "integrations"


def _get_collection(db: Optional[AsyncIOMotorDatabase], collection_name: str) -> AsyncIOMotorCollection:
    """Resolve an AsyncIOMotorCollection from either an explicit database
    instance or a module-level fallback. Raises if no database is available.

    This helper centralizes the multi-tenant collection resolution so callers
    can pass a tenant-specific ``db`` when needed.
    """
    if db is not None:
        return db.get_collection(collection_name)

    if _global_database is not None:
        # Support older code that provided a global `database` object that
        # behaves like an AsyncIOMotorDatabase.
        try:
            return _global_database.get_collection(collection_name)
        except Exception:
            # Some code used mapping access (database[collection_name])
            return _global_database[collection_name]

    raise RuntimeError(
        "No database available. Please pass a 'db' AsyncIOMotorDatabase "
        "instance to the function or configure app.database.database."
    )


async def list_integrations(
    db: Optional[AsyncIOMotorDatabase] = None, collection_name: str = DEFAULT_COLLECTION_NAME
) -> List[Integration]:
    """Return all integrations for the configured collection.

    Pass an explicit ``db`` for multi-tenant usage. This returns fully
    populated Integration models (including decrypted settings).
    """
    coll = _get_collection(db, collection_name)
    cursor = coll.find()
    integrations = await cursor.to_list(length=None)
    return [Integration(**integration) for integration in integrations]


async def list_integrations_summary(
    db: Optional[AsyncIOMotorDatabase] = None, collection_name: str = DEFAULT_COLLECTION_NAME, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Return a lightweight projection suitable for UI lists.

    The returned dicts include id, name, description and status and omit
    sensitive settings to avoid leaking secrets to list endpoints.
    """
    coll = _get_collection(db, collection_name)
    projection = {"settings": False}
    cursor = coll.find({}, projection=projection)
    integrations = await cursor.to_list(length=limit)
    # Ensure we expose a stable, JSON-serializable shape for the UI
    result: List[Dict[str, Any]] = []
    for doc in integrations:
        result.append(
            {
                "id": doc.get("id"),
                "name": doc.get("name"),
                "description": doc.get("description"),
                "status": doc.get("status"),
            }
        )
    return result


async def get_integration(
    id: str, db: Optional[AsyncIOMotorDatabase] = None, collection_name: str = DEFAULT_COLLECTION_NAME
) -> Optional[Integration]:
    """Get a specific integration by ID. Pass ``db`` for multi-tenant use.

    Returns an Integration model with decrypted settings or None if not found.
    """
    coll = _get_collection(db, collection_name)
    integration = await coll.find_one({"id": id})
    if integration:
        return Integration(**integration)
    return None


async def update_integration(
    id: str,
    integration: IntegrationUpdate,
    db: Optional[AsyncIOMotorDatabase] = None,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> Optional[Integration]:
    """Update an integration's fields.

    - Uses IntegrationUpdate.model_dump(exclude_unset=True) to avoid
      overwriting unspecified fields with None.
    - The IntegrationUpdate serializer will ensure sensitive settings are
      encrypted before persistence.
    - The function explicitly uses ReturnDocument.AFTER and handles missing
      documents to avoid silent failures.
    """
    coll = _get_collection(db, collection_name)

    update_data = integration.model_dump(exclude_unset=True)

    # If there's nothing to update, return the current document if present
    if not update_data:
        existing = await coll.find_one({"id": id})
        return Integration(**existing) if existing else None

    result = await coll.find_one_and_update(
        {"id": id}, {"$set": update_data}, return_document=ReturnDocument.AFTER
    )

    # If find_one_and_update returned None, the document may not exist.
    # Return None in that case to signal failure to update.
    if result is None:
        return None

    return Integration(**result)


async def ensure_default_integrations(db: Optional[AsyncIOMotorDatabase] = None, collection_name: str = DEFAULT_COLLECTION_NAME):
    """Ensure default integrations exist, encrypting sensitive settings.

    The function uses IntegrationCreate to ensure any sensitive values are
    encoded consistently with application usage before performing upserts.
    """
    coll = _get_collection(db, collection_name)

    default_integrations = [
        {
            "id": "facebook",
            "name": "Facebook Messenger",
            "description": "Connect with Facebook Messenger",
            "status": False,
            "settings": {
                "verify": "ai-chatbot-framework",
                "secret": "",
                "page_access_token": "",
            },
        },
        {
            "id": "chat_widget",
            "name": "Chat Widget",
            "description": "Add a chat widget to your website",
            "status": True,
            "settings": {},
        },
    ]

    for integration in default_integrations:
        # Use IntegrationCreate to apply encryption/serialization rules
        payload = IntegrationCreate(**integration).model_dump()
        await coll.update_one(
            {"id": integration["id"]}, {"$setOnInsert": payload}, upsert=True
        )