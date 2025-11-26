"""
Bot repository layer for CRUD operations.

This module provides async repository methods for managing bots in MongoDB.
All operations return Pydantic DTOs (Bot, NLUConfiguration) instead of raw dicts,
enabling easier migration to a dedicated microservice.

The repository interface is designed to be database-agnostic, allowing future
swapping of persistence layers without affecting consumers.

Import/export operations are delegated to the bots.exchange module to keep
CRUD operations focused and maintainable.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, List
from datetime import datetime
from bson import ObjectId

from app.admin.bots.schemas import Bot, NLUConfiguration
from app.database import get_collection


class BotRepository(ABC):
    """
    Abstract repository interface for bot persistence operations.
    
    Defines the contract for bot storage operations, enabling dependency
    injection and easier testing. All methods return Pydantic DTOs.
    """

    @abstractmethod
    async def ensure_default_bot(self) -> Bot:
        """
        Ensure the default bot exists, creating it if necessary.
        
        Returns:
            Bot: The default bot instance
        """
        pass

    @abstractmethod
    async def get_by_name(self, name: str) -> Optional[Bot]:
        """
        Retrieve a bot by name.
        
        Args:
            name: Bot name
            
        Returns:
            Bot: The bot if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_nlu_config(self, name: str) -> Optional[NLUConfiguration]:
        """
        Retrieve NLU configuration for a bot.
        
        Args:
            name: Bot name
            
        Returns:
            NLUConfiguration: The NLU config if bot exists, None otherwise
        """
        pass

    @abstractmethod
    async def update_nlu_config(self, name: str, nlu_config: dict) -> None:
        """
        Update NLU configuration for a bot.
        
        Args:
            name: Bot name
            nlu_config: Dictionary containing NLU configuration fields
        """
        pass


class MongoBotRepository(BotRepository):
    """
    MongoDB implementation of BotRepository.
    
    Provides async CRUD operations for bots stored in MongoDB.
    All operations return Pydantic DTOs for type safety.
    """

    def __init__(self):
        """Initialize repository with bot collection reference."""
        self._collection = get_collection("bot")

    async def ensure_default_bot(self) -> Bot:
        """
        Ensure the default bot exists, creating it if necessary.
        
        Checks for a bot named "default" and creates it with default
        NLU configuration if it doesn't exist.
        
        Returns:
            Bot: The default bot instance
        """
        default_bot = await self._collection.find_one({"name": "default"})
        if default_bot is None:
            default_bot_data = Bot(
                name="default",
                nlu_config=NLUConfiguration(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            await self._collection.insert_one(
                default_bot_data.model_dump(exclude={"id": True})
            )
            return default_bot_data
        return Bot.model_validate(default_bot)

    async def get_by_name(self, name: str) -> Optional[Bot]:
        """
        Retrieve a bot by name from MongoDB.
        
        Args:
            name: Bot name
            
        Returns:
            Bot: The bot if found, None otherwise
        """
        bot = await self._collection.find_one({"name": name})
        if bot is None:
            return None
        return Bot.model_validate(bot)

    async def get_nlu_config(self, name: str) -> Optional[NLUConfiguration]:
        """
        Retrieve NLU configuration for a bot.
        
        Args:
            name: Bot name
            
        Returns:
            NLUConfiguration: The NLU config if bot exists, None otherwise
        """
        bot = await self.get_by_name(name)
        if bot is None:
            return None
        return bot.nlu_config

    async def update_nlu_config(self, name: str, nlu_config: dict) -> None:
        """
        Update NLU configuration for a bot.
        
        Args:
            name: Bot name
            nlu_config: Dictionary containing NLU configuration fields
        """
        await self._collection.update_one(
            {"name": name}, 
            {"$set": {"nlu_config": nlu_config}}
        )


# Global repository instance for backward compatibility
_repository: Optional[BotRepository] = None


def set_repository(repository: BotRepository) -> None:
    """
    Set the global bot repository instance.
    
    Enables dependency injection of repository implementations for testing
    and future microservice extraction.
    
    Args:
        repository: BotRepository implementation to use globally
    """
    global _repository
    _repository = repository


def get_repository() -> BotRepository:
    """
    Get the global bot repository instance.
    
    Returns:
        BotRepository: The configured repository instance
        
    Raises:
        RuntimeError: If repository has not been initialized
    """
    if _repository is None:
        raise RuntimeError("Repository not initialized. Call set_repository() first.")
    return _repository


# Module-level convenience functions for backward compatibility
async def ensure_default_bot() -> Bot:
    """
    Ensure the default bot exists, creating it if necessary.
    
    Returns:
        Bot: The default bot instance
    """
    repo = get_repository()
    return await repo.ensure_default_bot()


async def get_bot(name: str) -> Optional[Bot]:
    """
    Retrieve a bot by name.
    
    Args:
        name: Bot name
        
    Returns:
        Bot: The bot if found, None otherwise
    """
    repo = get_repository()
    return await repo.get_by_name(name)


async def get_nlu_config(name: str) -> Optional[NLUConfiguration]:
    """
    Retrieve NLU configuration for a bot.
    
    Args:
        name: Bot name
        
    Returns:
        NLUConfiguration: The NLU config if bot exists, None otherwise
    """
    repo = get_repository()
    return await repo.get_nlu_config(name)


async def update_nlu_config(name: str, nlu_config: dict) -> None:
    """
    Update NLU configuration for a bot.
    
    Args:
        name: Bot name
        nlu_config: Dictionary containing NLU configuration fields
    """
    repo = get_repository()
    await repo.update_nlu_config(name, nlu_config)