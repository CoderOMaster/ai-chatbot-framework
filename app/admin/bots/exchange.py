"""
Bot import/export operations for configuration exchange.

This module handles bulk import and export of bot configurations including
intents and entities. Separated from store.py to keep CRUD operations focused
and maintainable.

Used by:
- Admin export/import API routes
- Configuration backup/restore workflows
- Bot migration between environments
"""

from typing import Dict, List

from app.admin.entities.store import list_entities, bulk_import_entities
from app.admin.intents.store import list_intents, bulk_import_intents


async def export_bot(name: str) -> Dict:
    """
    Export bot configuration including all intents and entities.
    
    Retrieves all intents and entities associated with the bot and
    serializes them for export (e.g., to JSON file or API response).
    
    Args:
        name: Bot name (currently unused as intents/entities are global,
              but included for future multi-tenant support)
        
    Returns:
        Dict with keys:
            - intents: List of intent dictionaries (excluding internal IDs)
            - entities: List of entity dictionaries (excluding internal IDs)
    """
    # Get all intents and entities
    intents_result = await list_intents()
    entities = await list_entities()

    # Handle both tuple return (intents, count) and list return for compatibility
    if isinstance(intents_result, tuple):
        intents, _ = intents_result
    else:
        intents = intents_result

    # Serialize to dictionaries, excluding internal MongoDB IDs
    entities_data = [entity.model_dump(exclude={"id"}) for entity in entities]
    intents_data = [
        intent.model_dump(exclude={"id": True, "parameters": {"__all__": {"id"}}})
        for intent in intents
    ]

    export_data = {"intents": intents_data, "entities": entities_data}
    return export_data


async def import_bot(name: str, data: Dict) -> Dict:
    """
    Import bot configuration including intents and entities.
    
    Performs bulk upsert of intents and entities from import data.
    Existing items are updated by name, new items are created.
    
    Args:
        name: Bot name (currently unused as intents/entities are global,
              but included for future multi-tenant support)
        data: Dictionary with keys:
            - intents: List of intent dictionaries to import
            - entities: List of entity dictionaries to import
        
    Returns:
        Dict with import statistics:
            - num_intents_created: Count of newly created intents
            - num_entities_created: Count of newly created entities
    """
    intents = data.get("intents", [])
    entities = data.get("entities", [])

    created_intents = await bulk_import_intents(intents)
    created_entities = await bulk_import_entities(entities)

    return {
        "num_intents_created": len(created_intents),
        "num_entities_created": len(created_entities),
    }