from typing import Optional
import logging
from app.bot.dialogue_manager.dialogue_manager import DialogueManager
from app.common import Settings

logger = logging.getLogger(__name__)

_dialogue_manager: Optional[DialogueManager] = None
_settings = Settings()


async def get_dialogue_manager() -> Optional[DialogueManager]:
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: DialogueManager) -> None:
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def init_dialogue_manager() -> None:
    global _dialogue_manager
    logger.info("initializing dialogue manager")
    _dialogue_manager = await DialogueManager.from_config()
    _dialogue_manager.update_model(_settings.MODELS_DIR)
    logger.info("dialogue manager initialized")


async def reload_dialogue_manager() -> None:
    """Reload the global dialogue manager object with new data and models."""

    dialogue_manager = await DialogueManager.from_config()
    dialogue_manager.update_model(_settings.MODELS_DIR)

    await set_dialogue_manager(dialogue_manager)
    logger.info("dialogue manager reloaded")