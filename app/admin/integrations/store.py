import logging
from typing import List, Optional

from app.database import database
from .schemas import Integration, IntegrationUpdate

logger = logging.getLogger(__name__)

collection_name = "integrations"


async def list_integrations() -> List[Integration]:
    """Get all integrations.
    
    Returns:
        List of Integration objects with sensitive data masked.
    """
    cursor = database[collection_name].find()
    integrations = await cursor.to_list(length=None)
    return [Integration(**integration) for integration in integrations]


async def get_integration(id: str) -> Optional[Integration]:
    """Get a specific integration by ID.
    
    Args:
        id: The integration identifier.
        
    Returns:
        Integration object with sensitive data masked, or None if not found.
    """
    integration = await database[collection_name].find_one({"id": id})
    if integration:
        return Integration(**integration)
    return None


async def update_integration(
    id: str, integration: IntegrationUpdate
) -> Optional[Integration]:
    """Update an integration's status and settings.
    
    Sensitive tokens in settings are never logged during updates.
    
    Args:
        id: The integration identifier.
        integration: The update payload with new settings.
        
    Returns:
        Updated Integration object with sensitive data masked, or None if not found.
    """
    update_data = integration.model_dump(exclude_unset=True)
    
    # Log update action without exposing sensitive settings
    logger.debug(
        "Updating integration",
        extra={"integration_id": id, "fields_updated": list(update_data.keys())},
    )

    result = await database[collection_name].find_one_and_update(
        {"id": id},
        {"$set": update_data},
        return_document=True,
    )

    if result:
        return Integration(**result)
    return None


async def ensure_default_integrations():
    """Ensure default integrations exist in the database.
    
    Initializes default integrations with empty sensitive fields.
    Sensitive tokens must be configured separately through secure channels.
    """
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
        await database[collection_name].update_one(
            {"id": integration["id"]},
            {"$setOnInsert": integration},
            upsert=True,
        )
        logger.debug(
            "Ensured default integration exists",
            extra={"integration_id": integration["id"]},
        )