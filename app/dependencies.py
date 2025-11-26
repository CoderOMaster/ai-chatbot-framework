"""
Dialogue Manager Lifecycle Module

Manages the initialization, reloading, and health status of the DialogueManager
singleton with proper locking for concurrent operations and health check integration.
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime

from app.bot.dialogue_manager.dialogue_manager import DialogueManager
from shared.config import app_config

logger = logging.getLogger(__name__)

# Global state
_dialogue_manager: Optional[DialogueManager] = None
_init_lock = asyncio.Lock()
_last_health_check: Optional[datetime] = None
_health_check_interval_seconds = 60


async def get_dialogue_manager() -> Optional[DialogueManager]:
    """
    Retrieve the current DialogueManager instance.

    Returns:
        DialogueManager instance or None if not initialized
    """
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: DialogueManager) -> None:
    """
    Set the DialogueManager instance with thread-safe locking.

    Args:
        dialogue_manager: DialogueManager instance to set
    """
    global _dialogue_manager
    async with _init_lock:
        _dialogue_manager = dialogue_manager
        logger.debug("DialogueManager instance updated")


async def init_dialogue_manager() -> DialogueManager:
    """
    Initialize the DialogueManager with proper locking for concurrent access.

    Ensures only one initialization occurs even with concurrent requests.
    Loads models from the configured models directory.

    Returns:
        Initialized DialogueManager instance

    Raises:
        Exception: If initialization fails
    """
    global _dialogue_manager

    async with _init_lock:
        # Check if already initialized
        if _dialogue_manager is not None:
            logger.debug("DialogueManager already initialized, returning existing instance")
            return _dialogue_manager

        try:
            logger.info("Initializing dialogue manager")
            _dialogue_manager = await DialogueManager.from_config()
            _dialogue_manager.update_model(app_config.MODELS_DIR)
            logger.info("Dialogue manager initialized successfully")
            return _dialogue_manager
        except Exception as e:
            logger.error(f"Failed to initialize dialogue manager: {e}", exc_info=True)
            _dialogue_manager = None
            raise


async def reload_dialogue_manager() -> DialogueManager:
    """
    Reload the DialogueManager with new data and models with proper locking.

    Recreates the dialogue manager instance with fresh configuration and models.
    Ensures atomic replacement of the instance.

    Returns:
        Reloaded DialogueManager instance

    Raises:
        Exception: If reload fails
    """
    global _dialogue_manager

    async with _init_lock:
        try:
            logger.info("Reloading dialogue manager")

            # Create new instance with fresh configuration
            new_dialogue_manager = await DialogueManager.from_config()

            # Update with latest models
            new_dialogue_manager.update_model(app_config.MODELS_DIR)

            # Atomically replace the instance
            _dialogue_manager = new_dialogue_manager

            logger.info("Dialogue manager reloaded successfully")
            return _dialogue_manager
        except Exception as e:
            logger.error(f"Failed to reload dialogue manager: {e}", exc_info=True)
            raise


async def health_check() -> dict:
    """
    Perform health check on the DialogueManager instance.

    Verifies that the DialogueManager is initialized and operational.
    Includes basic status information for monitoring.

    Returns:
        Dictionary with health status:
        {
            "status": "healthy" | "unhealthy",
            "initialized": bool,
            "last_check": datetime,
            "message": str
        }
    """
    global _last_health_check

    _last_health_check = datetime.utcnow()

    if _dialogue_manager is None:
        logger.warning("Health check failed: DialogueManager not initialized")
        return {
            "status": "unhealthy",
            "initialized": False,
            "last_check": _last_health_check,
            "message": "DialogueManager not initialized"
        }

    try:
        # Verify NLU pipeline is loaded
        if _dialogue_manager.nlu_pipeline is None:
            logger.warning("Health check failed: NLU pipeline not initialized")
            return {
                "status": "unhealthy",
                "initialized": True,
                "last_check": _last_health_check,
                "message": "NLU pipeline not initialized"
            }

        logger.debug("Health check passed")
        return {
            "status": "healthy",
            "initialized": True,
            "last_check": _last_health_check,
            "message": "DialogueManager operational"
        }
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "initialized": True,
            "last_check": _last_health_check,
            "message": f"Health check error: {str(e)}"
        }


async def get_health_status() -> dict:
    """
    Get the last recorded health status without performing a new check.

    Returns:
        Dictionary with cached health status or None if no check performed
    """
    if _last_health_check is None:
        return {
            "status": "unknown",
            "initialized": _dialogue_manager is not None,
            "last_check": None,
            "message": "No health check performed yet"
        }

    return {
        "status": "healthy" if _dialogue_manager is not None else "unhealthy",
        "initialized": _dialogue_manager is not None,
        "last_check": _last_health_check,
        "message": "Last recorded status"
    }