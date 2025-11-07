from typing import Optional
from app.bot.dialogue_manager.dialogue_manager import DialogueManager
from ai_chatbot_common.config import get_settings
import logging

logger = logging.getLogger(__name__)

_dialogue_manager: Optional[DialogueManager] = None


async def get_dialogue_manager() -> Optional[DialogueManager]:
    """FastAPI dependency to retrieve the current DialogueManager instance.

    Use set_dialogue_manager during application startup to inject the instance.
    """
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: DialogueManager) -> None:
    """Set the process-wide DialogueManager instance.

    This is invoked from the FastAPI lifespan hook. Tests may override it.
    """
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def init_dialogue_manager() -> None:
    """Initialize and inject the DialogueManager using configuration settings."""
    global _dialogue_manager
    logger.info("initializing dialogue manager")
    _dialogue_manager = await DialogueManager.from_config()
    # Load/update trained models directory from Settings
    settings = get_settings()
    _dialogue_manager.update_model(settings.MODELS_DIR)
    logger.info("dialogue manager initialized")


async def reload_dialogue_manager() -> None:
    """Reload the DialogueManager with new data and models."""
    # recreate dialogue manager with new data
    dialogue_manager = await DialogueManager.from_config()

    # update dialogue manager with new models
    settings = get_settings()
    dialogue_manager.update_model(settings.MODELS_DIR)

    await set_dialogue_manager(dialogue_manager)

    logger.info("dialogue manager reloaded")