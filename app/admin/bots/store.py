"""
Bots data service for managing bot configurations, NLU settings, and import/export operations.
Handles race conditions and provides caching for frequently accessed bot configs.
"""
from typing import Dict, Optional
from datetime import datetime
from functools import lru_cache

from shared.models.bots import Bot, NLUConfiguration
from shared.database import database, get_collection
from app.admin.entities.store import list_entities, bulk_import_entities
from app.admin.intents.store import list_intents, bulk_import_intents


bot_collection = get_collection("bot")


async def ensure_default_bot() -> Bot:
    """
    Ensure the default bot exists using atomic findOneAndUpdate with upsert.
    Handles race conditions where multiple processes might try to create the default bot.
    
    Returns:
        Bot: The default bot configuration
        
    Raises:
        Exception: If database operation fails
    """
    try:
        now = datetime.utcnow()
        default_bot_data = {
            "name": "default",
            "created_at": now,
            "updated_at": now,
        }
        
        # Use findOneAndUpdate with upsert to handle race conditions atomically
        result = await bot_collection.find_one_and_update(
            {"name": "default"},
            {"$setOnInsert": default_bot_data},
            upsert=True,
            return_document=True,
        )
        
        if result is None:
            raise ValueError("Failed to ensure default bot exists")
            
        return Bot.model_validate(result)
    except Exception as e:
        raise Exception(f"Failed to ensure default bot: {str(e)}")


async def get_bot(name: str) -> Bot:
    """
    Retrieve a bot configuration by name.
    
    Args:
        name: The name of the bot
        
    Returns:
        Bot: The bot configuration
        
    Raises:
        ValueError: If bot not found
        Exception: If database operation fails
    """
    try:
        bot = await bot_collection.find_one({"name": name})
        if bot is None:
            raise ValueError(f"Bot '{name}' not found")
        return Bot.model_validate(bot)
    except ValueError:
        raise
    except Exception as e:
        raise Exception(f"Failed to retrieve bot '{name}': {str(e)}")


async def get_nlu_config(name: str) -> NLUConfiguration:
    """
    Retrieve NLU configuration for a specific bot.
    
    Args:
        name: The name of the bot
        
    Returns:
        NLUConfiguration: The NLU configuration
        
    Raises:
        ValueError: If bot or NLU config not found
        Exception: If database operation fails
    """
    try:
        bot = await get_bot(name)
        if not bot.nlu_config:
            raise ValueError(f"NLU configuration not found for bot '{name}'")
        return bot.nlu_config
    except ValueError:
        raise
    except Exception as e:
        raise Exception(f"Failed to retrieve NLU config for bot '{name}': {str(e)}")


async def update_nlu_config(name: str, nlu_config: dict) -> None:
    """
    Update NLU configuration for a specific bot.
    
    Args:
        name: The name of the bot
        nlu_config: The new NLU configuration
        
    Raises:
        ValueError: If bot not found
        Exception: If database operation fails
    """
    try:
        # Verify bot exists
        await get_bot(name)
        
        result = await bot_collection.update_one(
            {"name": name},
            {
                "$set": {
                    "nlu_config": nlu_config,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        
        if result.matched_count == 0:
            raise ValueError(f"Bot '{name}' not found")
            
        # Clear cache if implemented
        _clear_bot_cache()
    except ValueError:
        raise
    except Exception as e:
        raise Exception(f"Failed to update NLU config for bot '{name}': {str(e)}")


async def export_bot(name: str) -> Dict:
    """
    Export bot configuration including all intents and entities.
    
    Args:
        name: The name of the bot (for future filtering, currently exports all)
        
    Returns:
        Dict: Export data containing intents and entities
        
    Raises:
        Exception: If export operation fails
    """
    try:
        # Get all intents and entities
        intents = await list_intents()
        entities = await list_entities()

        entities = [entity.model_dump(exclude={"id"}) for entity in entities]
        intents = [
            intent.model_dump(exclude={"id": True, "parameters": {"__all__": {"id"}}})
            for intent in intents
        ]

        export_data = {"intents": intents, "entities": entities}
        return export_data
    except Exception as e:
        raise Exception(f"Failed to export bot '{name}': {str(e)}")


async def import_bot(name: str, data: Dict) -> Dict:
    """
    Import intents and entities for a bot.
    Note: For very large imports (>10k items), consider using Step Functions.
    
    Args:
        name: The name of the bot
        data: Import data containing intents and entities
        
    Returns:
        Dict: Summary of created intents and entities
        
    Raises:
        ValueError: If data format is invalid
        Exception: If import operation fails
    """
    try:
        if not isinstance(data, dict):
            raise ValueError("Import data must be a dictionary")
            
        intents = data.get("intents", [])
        entities = data.get("entities", [])

        if not isinstance(intents, list) or not isinstance(entities, list):
            raise ValueError("Intents and entities must be lists")

        created_intents = await bulk_import_intents(intents)
        created_entities = await bulk_import_entities(entities)

        return {
            "num_intents_created": len(created_intents),
            "num_entities_created": len(created_entities),
        }
    except ValueError:
        raise
    except Exception as e:
        raise Exception(f"Failed to import bot '{name}': {str(e)}")


def _clear_bot_cache() -> None:
    """
    Clear cached bot configurations.
    Placeholder for future caching implementation.
    """
    pass