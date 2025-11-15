from typing import List, Optional
from app.common.config import Settings
from app.common.database import get_db
from .schemas import Integration, IntegrationUpdate

collection_name = "integrations"
_settings = Settings()


async def _collection():
    db = await get_db(_settings)
    return db[collection_name]


async def list_integrations() -> List[Integration]:
    """Get all integrations."""
    col = await _collection()
    cursor = col.find()
    integrations = await cursor.to_list(length=None)
    return [Integration(**integration) for integration in integrations]


async def get_integration(id: str) -> Optional[Integration]:
    """Get a specific integration by ID."""
    col = await _collection()
    integration = await col.find_one({"id": id})
    if integration:
        return Integration(**integration)
    return None


async def update_integration(
    id: str, integration: IntegrationUpdate
) -> Optional[Integration]:
    """Update an integration's status and settings."""
    col = await _collection()
    update_data = integration.model_dump(exclude_unset=True)

    result = await col.find_one_and_update(
        {"id": id},
        {"$set": update_data},
        return_document=True,
    )

    if result:
        return Integration(**result)
    return None


async def ensure_default_integrations():
    """Ensure default integrations exist in the database."""
    col = await _collection()
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
        await col.update_one(
            {"id": integration["id"]},
            {"$setOnInsert": integration},
            upsert=True,
        )