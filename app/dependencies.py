from typing import Optional
import logging

from ai_chatbot_common.config import get_settings
# Import the dialogue manager via local package, but construct via DI-friendly helpers
from app.bot.dialogue_manager.dialogue_manager import DialogueManager

logger = logging.getLogger(__name__)

_dialogue_manager: Optional[DialogueManager] = None


async def get_dialogue_manager() -> Optional[DialogueManager]:
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: Optional[DialogueManager]):
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def init_dialogue_manager():
    """Initialize the DialogueManager instance without loading heavy NLU locally.
    The DialogueManager should call the external NLU runtime (from 5.1) using HTTP.
    """
    global _dialogue_manager
    logger.info("initializing dialogue manager")
    settings = get_settings()

    # Construct DialogueManager using its factory; ensure it is configured to use remote NLU
    _dialogue_manager = await DialogueManager.from_config()
    # Do NOT load models in core API; ensure DM points to remote NLU runtime
    if hasattr(_dialogue_manager, "update_model"):
        logger.info("skipping local model load; DialogueManager should call NLU runtime externally")
    logger.info("dialogue manager initialized")


async def reload_dialogue_manager():
    """Recreate DialogueManager to pick up new configuration without process restart."""
    dm = await DialogueManager.from_config()
    await set_dialogue_manager(dm)
    logger.info("dialogue manager reloaded")