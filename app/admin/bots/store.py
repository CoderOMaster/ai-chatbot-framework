"""Bot configuration store with error handling, retry logic, and caching."""
import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime
from functools import lru_cache

from app.admin.bots.schemas import Bot, NLUConfiguration
from app.database import get_database

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_TTL_SECONDS = 300
MAX_RETRIES = 3
INITIAL_BACKOFF_MS = 100
MAX_BACKOFF_MS = 5000


class BotStoreError(Exception):
    """Base exception for bot store operations."""
    pass


class BotNotFoundError(BotStoreError):
    """Raised when a bot is not found."""
    pass


class BotAlreadyExistsError(BotStoreError):
    """Raised when attempting to create a bot that already exists."""
    pass


class BotStoreService:
    """Service class for bot store operations with caching and error handling."""

    def __init__(self):
        """Initialize the bot store service."""
        self._cache: Dict[str, tuple[Bot, float]] = {}
        self._index_created = False

    async def _get_collection(self):
        """Get the bot collection with error handling.
        
        Returns:
            Motor collection for bots
            
        Raises:
            BotStoreError: If database connection fails
        """
        try:
            database = await get_database()
            return database.get_collection("bot")
        except Exception as e:
            logger.error(f"Failed to get bot collection: {e}")
            raise BotStoreError(f"Database connection failed: {e}") from e

    async def _ensure_indexes(self) -> None:
        """Create unique index on bot name if not already created.
        
        Raises:
            BotStoreError: If index creation fails
        """
        if self._index_created:
            return

        try:
            collection = await self._get_collection()
            await collection.create_index("name", unique=True)
            self._index_created = True
            logger.info("Bot name unique index created successfully")
        except Exception as e:
            logger.error(f"Failed to create bot name index: {e}")
            raise BotStoreError(f"Index creation failed: {e}") from e

    async def _retry_with_backoff(self, coro, operation_name: str):
        """Execute async operation with exponential backoff retry logic.
        
        Args:
            coro: Coroutine to execute
            operation_name: Name of the operation for logging
            
        Returns:
            Result of the coroutine
            
        Raises:
            BotStoreError: If all retry attempts fail
        """
        backoff_ms = INITIAL_BACKOFF_MS
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                return await coro
            except Exception as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"{operation_name} attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {backoff_ms}ms..."
                    )
                    await asyncio.sleep(backoff_ms / 1000)
                    backoff_ms = min(backoff_ms * 2, MAX_BACKOFF_MS)
                else:
                    logger.error(
                        f"{operation_name} failed after {MAX_RETRIES} attempts: {e}"
                    )

        raise BotStoreError(
            f"{operation_name} failed after {MAX_RETRIES} attempts: {last_exception}"
        ) from last_exception

    def _invalidate_cache(self, bot_name: Optional[str] = None) -> None:
        """Invalidate cache entries.
        
        Args:
            bot_name: Specific bot name to invalidate, or None to clear all
        """
        if bot_name:
            self._cache.pop(bot_name, None)
            logger.debug(f"Cache invalidated for bot: {bot_name}")
        else:
            self._cache.clear()
            logger.debug("Cache cleared")

    def _get_cached_bot(self, bot_name: str) -> Optional[Bot]:
        """Get bot from cache if available and not expired.
        
        Args:
            bot_name: Name of the bot
            
        Returns:
            Cached Bot or None if not in cache or expired
        """
        if bot_name in self._cache:
            bot, timestamp = self._cache[bot_name]
            if datetime.utcnow().timestamp() - timestamp < CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for bot: {bot_name}")
                return bot
            else:
                self._invalidate_cache(bot_name)

        return None

    def _set_cached_bot(self, bot: Bot) -> None:
        """Store bot in cache with timestamp.
        
        Args:
            bot: Bot to cache
        """
        self._cache[bot.name] = (bot, datetime.utcnow().timestamp())
        logger.debug(f"Bot cached: {bot.name}")

    async def ensure_default_bot(self) -> Bot:
        """Ensure the default bot exists, creating it if necessary.
        
        Returns:
            The default Bot instance
            
        Raises:
            BotStoreError: If database operation fails
        """
        await self._ensure_indexes()

        async def _create_default():
            collection = await self._get_collection()
            default_bot = await collection.find_one({"name": "default"})
            
            if default_bot is None:
                bot_data = Bot(name="default")
                bot_data.created_at = datetime.utcnow()
                bot_data.updated_at = datetime.utcnow()
                
                try:
                    await collection.insert_one(
                        bot_data.model_dump(exclude={"id": True})
                    )
                    self._set_cached_bot(bot_data)
                    logger.info("Default bot created successfully")
                    return bot_data
                except Exception as e:
                    logger.error(f"Failed to create default bot: {e}")
                    raise
            
            bot = Bot.model_validate(default_bot)
            self._set_cached_bot(bot)
            return bot

        return await self._retry_with_backoff(_create_default(), "ensure_default_bot")

    async def get_bot(self, name: str) -> Bot:
        """Get a bot by name with caching.
        
        Args:
            name: Name of the bot
            
        Returns:
            The Bot instance
            
        Raises:
            BotNotFoundError: If bot does not exist
            BotStoreError: If database operation fails
        """
        # Check cache first
        cached_bot = self._get_cached_bot(name)
        if cached_bot:
            return cached_bot

        async def _fetch_bot():
            collection = await self._get_collection()
            bot_doc = await collection.find_one({"name": name})
            
            if bot_doc is None:
                logger.warning(f"Bot not found: {name}")
                raise BotNotFoundError(f"Bot '{name}' not found")
            
            bot = Bot.model_validate(bot_doc)
            self._set_cached_bot(bot)
            return bot

        return await self._retry_with_backoff(_fetch_bot(), f"get_bot({name})")

    async def get_nlu_config(self, name: str) -> NLUConfiguration:
        """Get NLU configuration for a bot.
        
        Args:
            name: Name of the bot
            
        Returns:
            The NLUConfiguration instance
            
        Raises:
            BotNotFoundError: If bot does not exist
            BotStoreError: If database operation fails
        """
        bot = await self.get_bot(name)
        return bot.nlu_config

    async def update_nlu_config(self, name: str, nlu_config: dict) -> None:
        """Update NLU configuration for a bot.
        
        Args:
            name: Name of the bot
            nlu_config: New NLU configuration dictionary
            
        Raises:
            BotNotFoundError: If bot does not exist
            BotStoreError: If database operation fails
        """
        async def _update_config():
            collection = await self._get_collection()
            result = await collection.update_one(
                {"name": name},
                {
                    "$set": {
                        "nlu_config": nlu_config,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.matched_count == 0:
                logger.warning(f"Bot not found for update: {name}")
                raise BotNotFoundError(f"Bot '{name}' not found")
            
            self._invalidate_cache(name)
            logger.info(f"NLU config updated for bot: {name}")

        return await self._retry_with_backoff(
            _update_config(), f"update_nlu_config({name})"
        )

    async def export_bot(self, name: str) -> Dict:
        """Export bot configuration with intents and entities.
        
        Args:
            name: Name of the bot
            
        Returns:
            Dictionary containing intents and entities
            
        Raises:
            BotNotFoundError: If bot does not exist
            BotStoreError: If database operation fails
        """
        # Verify bot exists
        await self.get_bot(name)

        async def _export():
            # Import here to avoid circular imports and support microservice extraction
            try:
                from app.admin.intents.store import list_intents
                from app.admin.entities.store import list_entities
            except ImportError as e:
                logger.error(f"Failed to import store modules: {e}")
                raise BotStoreError(f"Failed to load store modules: {e}") from e

            try:
                intents = await list_intents()
                entities = await list_entities()

                entities_data = [
                    entity.model_dump(exclude={"id"}) for entity in entities
                ]
                intents_data = [
                    intent.model_dump(
                        exclude={"id": True, "parameters": {"__all__": {"id"}}}
                    )
                    for intent in intents
                ]

                export_data = {"intents": intents_data, "entities": entities_data}
                logger.info(f"Bot exported successfully: {name}")
                return export_data
            except Exception as e:
                logger.error(f"Failed to export bot data: {e}")
                raise

        return await self._retry_with_backoff(_export(), f"export_bot({name})")

    async def import_bot(self, name: str, data: Dict) -> Dict:
        """Import bot configuration with transaction support.
        
        Args:
            name: Name of the bot
            data: Dictionary containing intents and entities to import
            
        Returns:
            Dictionary with counts of created intents and entities
            
        Raises:
            BotNotFoundError: If bot does not exist
            BotStoreError: If database operation fails
        """
        # Verify bot exists
        await self.get_bot(name)

        async def _import():
            # Import here to avoid circular imports and support microservice extraction
            try:
                from app.admin.intents.store import bulk_import_intents
                from app.admin.entities.store import bulk_import_entities
            except ImportError as e:
                logger.error(f"Failed to import store modules: {e}")
                raise BotStoreError(f"Failed to load store modules: {e}") from e

            try:
                intents = data.get("intents", [])
                entities = data.get("entities", [])

                # Execute imports with transaction-like semantics
                created_intents = await bulk_import_intents(intents)
                created_entities = await bulk_import_entities(entities)

                # Update bot's updated_at timestamp
                collection = await self._get_collection()
                await collection.update_one(
                    {"name": name},
                    {"$set": {"updated_at": datetime.utcnow()}}
                )

                self._invalidate_cache(name)
                logger.info(
                    f"Bot import completed: {name} "
                    f"({len(created_intents)} intents, {len(created_entities)} entities)"
                )

                return {
                    "num_intents_created": len(created_intents),
                    "num_entities_created": len(created_entities),
                }
            except Exception as e:
                logger.error(f"Failed to import bot data: {e}")
                raise

        return await self._retry_with_backoff(_import(), f"import_bot({name})")


# Global service instance
_bot_store_service = BotStoreService()


async def get_bot_store_service() -> BotStoreService:
    """Get the global bot store service instance.
    
    Returns:
        BotStoreService instance
    """
    return _bot_store_service


# Legacy function wrappers for backwards compatibility
async def ensure_default_bot() -> Bot:
    """Ensure the default bot exists.
    
    Returns:
        The default Bot instance
    """
    service = await get_bot_store_service()
    return await service.ensure_default_bot()


async def get_bot(name: str) -> Bot:
    """Get a bot by name.
    
    Args:
        name: Name of the bot
        
    Returns:
        The Bot instance
    """
    service = await get_bot_store_service()
    return await service.get_bot(name)


async def get_nlu_config(name: str) -> NLUConfiguration:
    """Get NLU configuration for a bot.
    
    Args:
        name: Name of the bot
        
    Returns:
        The NLUConfiguration instance
    """
    service = await get_bot_store_service()
    return await service.get_nlu_config(name)


async def update_nlu_config(name: str, nlu_config: dict) -> None:
    """Update NLU configuration for a bot.
    
    Args:
        name: Name of the bot
        nlu_config: New NLU configuration dictionary
    """
    service = await get_bot_store_service()
    return await service.update_nlu_config(name, nlu_config)


async def export_bot(name: str) -> Dict:
    """Export bot configuration with intents and entities.
    
    Args:
        name: Name of the bot
        
    Returns:
        Dictionary containing intents and entities
    """
    service = await get_bot_store_service()
    return await service.export_bot(name)


async def import_bot(name: str, data: Dict) -> Dict:
    """Import bot configuration.
    
    Args:
        name: Name of the bot
        data: Dictionary containing intents and entities to import
        
    Returns:
        Dictionary with counts of created intents and entities
    """
    service = await get_bot_store_service()
    return await service.import_bot(name, data)


__all__ = [
    "BotStoreService",
    "BotStoreError",
    "BotNotFoundError",
    "BotAlreadyExistsError",
    "get_bot_store_service",
    "ensure_default_bot",
    "get_bot",
    "get_nlu_config",
    "update_nlu_config",
    "export_bot",
    "import_bot",
]