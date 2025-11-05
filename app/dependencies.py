from typing import Optional
import logging

from app.bot.dialogue_manager.dialogue_manager import DialogueManager
from app.common.config import get_settings
from app.database import init_database, close_database, database, get_db, check_db_connection
from app.bot.memory.memory_saver_mongo import MemorySaverMongo

logger = logging.getLogger(__name__)

# Internal cached dialogue manager reference. Services should use the
# provided get_/set_ helpers which are async-compatible with FastAPI
# lifecycles.
_dialogue_manager: Optional[DialogueManager] = None


async def get_dialogue_manager():
    """Return the currently initialized DialogueManager or None.

    This is intended to be used as a dependency in FastAPI endpoints or
    startup/shutdown events.
    """
    global _dialogue_manager
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: DialogueManager):
    """Set the global dialogue manager reference."""
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def init_dialogue_manager():
    """Create and initialize the DialogueManager using application Settings.

    This now initializes the DB connection first (init_database) and then
    constructs the DialogueManager instance by passing in an injected
    MemorySaverMongo bound to the runtime database instance. This decouples
    DB lifecycle and makes the DialogueManager easier to test and restart.
    """
    global _dialogue_manager
    settings = get_settings()
    logger.info("initializing database and dialogue manager")

    # initialize DB singletons
    init_database(settings)

    # construct memory saver using module-level database
    dm = await DialogueManager.from_config(database=database)

    # apply any configured models_dir
    dm.update_model(settings.MODELS_DIR)

    _dialogue_manager = dm
    logger.info("dialogue manager initialized")


async def reload_dialogue_manager():
    """Reload the global dialogue manager object with new data and models."""

    # recreate dialogue manager with new data
    dialogue_manager = await DialogueManager.from_config(database=database)

    # update dialogue manager with new models
    settings = get_settings()
    dialogue_manager.update_model(settings.MODELS_DIR)

    await set_dialogue_manager(dialogue_manager)

    logger.info("dialogue manager reloaded")