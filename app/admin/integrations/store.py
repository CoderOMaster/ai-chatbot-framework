from typing import List, Optional
from shared.database import database
from shared.models.integrations import Integration, IntegrationUpdate

collection_name = "integrations"


async def list_integrations() -> List[Integration]:
    """Get all integrations.
    
    Returns:
        List of all integrations from the database.
        
    Raises:
        Exception: If database query fails.
    """
    try:
        cursor = database[collection_name].find()
        integrations = await cursor.to_list(length=None)
        return [Integration(**integration) for integration in integrations]
    except Exception as e:
        raise Exception(f"Failed to list integrations: {str(e)}")


async def get_integration(id: str) -> Optional[Integration]:
    """Get a specific integration by ID.
    
    Args:
        id: The integration ID.
        
    Returns:
        Integration object if found, None otherwise.
        
    Raises:
        Exception: If database query fails.
    """
    try:
        integration = await database[collection_name].find_one({"id": id})
        if integration:
            return Integration(**integration)
        return None
    except Exception as e:
        raise Exception(f"Failed to get integration {id}: {str(e)}")


async def update_integration(
    id: str, integration: IntegrationUpdate
) -> Optional[Integration]:
    """Update an integration's status and settings.
    
    Args:
        id: The integration ID.
        integration: The update data.
        
    Returns:
        Updated Integration object if found, None otherwise.
        
    Raises:
        Exception: If database operation fails.
    """
    try:
        update_data = integration.model_dump(exclude_unset=True)

        result = await database[collection_name].find_one_and_update(
            {"id": id},
            {"$set": update_data},
            return_document=True,
        )

        if result:
            return Integration(**result)
        return None
    except Exception as e:
        raise Exception(f"Failed to update integration {id}: {str(e)}")