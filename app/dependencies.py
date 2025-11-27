"""FastAPI dependency injection and lifecycle management.

This module provides dependency injection helpers for FastAPI, managing
the lifecycle of the DialogueManager and related services with proper
initialization, shutdown, and reload capabilities.
"""

from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
import asyncio
import logging

from app.bot.dialogue_manager.dialogue_manager import DialogueManager
from app.config import app_config

logger = logging.getLogger(__name__)


class DialogueManagerContainer:
    """Container for managing DialogueManager lifecycle with thread-safe access.
    
    This replaces the singleton pattern with a proper dependency container
    that supports graceful shutdown and reload without downtime.
    """
    
    def __init__(self) -> None:
        """Initialize the dialogue manager container."""
        self._dialogue_manager: Optional[DialogueManager] = None
        self._lock = asyncio.Lock()
        self._is_shutting_down = False
    
    async def get(self) -> DialogueManager:
        """Get the current dialogue manager instance.
        
        Returns:
            DialogueManager: The current dialogue manager instance
            
        Raises:
            RuntimeError: If manager is not initialized or is shutting down
        """
        if self._is_shutting_down:
            raise RuntimeError("DialogueManager is shutting down")
        
        if self._dialogue_manager is None:
            raise RuntimeError("DialogueManager not initialized. Call init() first.")
        
        return self._dialogue_manager
    
    async def init(self) -> None:
        """Initialize the dialogue manager from configuration.
        
        Raises:
            RuntimeError: If already initialized or initialization fails
        """
        async with self._lock:
            if self._dialogue_manager is not None:
                raise RuntimeError("DialogueManager already initialized")
            
            logger.info("Initializing dialogue manager")
            try:
                self._dialogue_manager = await DialogueManager.from_config()
                self._dialogue_manager.update_model(app_config.MODELS_DIR)
                logger.info("Dialogue manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize dialogue manager: {e}", exc_info=True)
                raise
    
    async def reload(self) -> None:
        """Reload the dialogue manager with new data and models without downtime.
        
        This method creates a new instance while keeping the old one available,
        then atomically swaps them to ensure no requests are dropped.
        
        Raises:
            RuntimeError: If reload fails
        """
        async with self._lock:
            if self._dialogue_manager is None:
                raise RuntimeError("DialogueManager not initialized")
            
            logger.info("Starting dialogue manager reload")
            try:
                # Create new instance
                new_manager = await DialogueManager.from_config()
                new_manager.update_model(app_config.MODELS_DIR)
                
                # Atomic swap
                old_manager = self._dialogue_manager
                self._dialogue_manager = new_manager
                
                logger.info("Dialogue manager reloaded successfully")
                
                # Cleanup old manager if it has a cleanup method
                if hasattr(old_manager, 'cleanup'):
                    try:
                        await old_manager.cleanup()
                    except Exception as e:
                        logger.warning(f"Error cleaning up old manager: {e}")
                        
            except Exception as e:
                logger.error(f"Failed to reload dialogue manager: {e}", exc_info=True)
                raise
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the dialogue manager.
        
        This method ensures no new requests are accepted and waits for
        the manager to complete any ongoing operations.
        """
        async with self._lock:
            self._is_shutting_down = True
            
            if self._dialogue_manager is None:
                logger.info("No dialogue manager to shutdown")
                return
            
            logger.info("Shutting down dialogue manager")
            try:
                # Call cleanup if available
                if hasattr(self._dialogue_manager, 'cleanup'):
                    await self._dialogue_manager.cleanup()
                
                # Close memory saver connections
                if hasattr(self._dialogue_manager, 'memory_saver'):
                    memory_saver = self._dialogue_manager.memory_saver
                    if hasattr(memory_saver, 'close'):
                        await memory_saver.close()
                
                self._dialogue_manager = None
                logger.info("Dialogue manager shutdown complete")
                
            except Exception as e:
                logger.error(f"Error during dialogue manager shutdown: {e}", exc_info=True)
    
    async def health_check(self) -> dict:
        """Perform health check on the dialogue manager.
        
        Returns:
            dict: Health status with keys:
                - status: "healthy" or "unhealthy"
                - initialized: bool indicating if manager is initialized
                - shutting_down: bool indicating if shutdown is in progress
                - error: optional error message if unhealthy
        """
        try:
            if self._is_shutting_down:
                return {
                    "status": "unhealthy",
                    "initialized": False,
                    "shutting_down": True,
                    "error": "DialogueManager is shutting down"
                }
            
            if self._dialogue_manager is None:
                return {
                    "status": "unhealthy",
                    "initialized": False,
                    "shutting_down": False,
                    "error": "DialogueManager not initialized"
                }
            
            # Check if NLU pipeline is available
            if self._dialogue_manager.nlu_pipeline is None:
                return {
                    "status": "unhealthy",
                    "initialized": True,
                    "shutting_down": False,
                    "error": "NLU pipeline not initialized"
                }
            
            return {
                "status": "healthy",
                "initialized": True,
                "shutting_down": False,
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "initialized": False,
                "shutting_down": False,
                "error": str(e)
            }


# Global container instance
_container = DialogueManagerContainer()


async def get_dialogue_manager() -> DialogueManager:
    """FastAPI dependency for getting the dialogue manager.
    
    This function is used as a dependency in FastAPI route handlers:
    
    Example:
        @app.get("/chat")
        async def chat(manager: DialogueManager = Depends(get_dialogue_manager)):
            return await manager.process(message)
    
    Returns:
        DialogueManager: The current dialogue manager instance
        
    Raises:
        RuntimeError: If manager is not initialized
    """
    return await _container.get()


async def init_dialogue_manager() -> None:
    """Initialize the dialogue manager.
    
    This should be called during application startup.
    
    Raises:
        RuntimeError: If initialization fails
    """
    await _container.init()


async def reload_dialogue_manager() -> None:
    """Reload the dialogue manager with new data and models.
    
    This should be called when models are updated or configuration changes.
    Supports reload without downtime.
    
    Raises:
        RuntimeError: If reload fails
    """
    await _container.reload()


async def shutdown_dialogue_manager() -> None:
    """Gracefully shutdown the dialogue manager.
    
    This should be called during application shutdown.
    """
    await _container.shutdown()


async def health_check_dialogue_manager() -> dict:
    """Perform health check on the dialogue manager.
    
    Returns:
        dict: Health status information
    """
    return await _container.health_check()


@asynccontextmanager
async def lifespan_manager():
    """FastAPI lifespan context manager for application startup and shutdown.
    
    This manages the complete lifecycle of the DialogueManager:
    - Initializes on startup
    - Gracefully shuts down on application termination
    
    Usage in FastAPI:
        app = FastAPI(lifespan=lifespan_manager)
    
    Yields:
        None
    """
    # Startup
    try:
        await init_dialogue_manager()
        logger.info("Application startup complete")
        yield
    finally:
        # Shutdown
        await shutdown_dialogue_manager()
        logger.info("Application shutdown complete")