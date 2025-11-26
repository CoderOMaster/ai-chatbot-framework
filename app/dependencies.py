"""
Dependency injection helpers for FastAPI application.

This module provides factory functions and provider patterns for core application
dependencies like DialogueManager. Supports both in-process instances and remote
microservice clients through a pluggable provider interface.

The module uses dependency injection to allow API layers to obtain dialogue manager
instances without holding global state, enabling flexible deployment patterns
(monolith or microservice-based).
"""

from typing import Optional, Protocol, Union
from abc import ABC, abstractmethod
import logging

from app.bot.dialogue_manager.dialogue_manager import DialogueManager
from app.common.config import get_settings

logger = logging.getLogger(__name__)


class DialogueManagerProvider(ABC):
    """
    Abstract base class for dialogue manager providers.
    
    Defines the interface for obtaining dialogue manager instances,
    supporting both in-process and remote microservice implementations.
    """

    @abstractmethod
    async def get(self) -> Union[DialogueManager, "DialogueManagerClient"]:
        """
        Get a dialogue manager instance or client.
        
        Returns:
            Union[DialogueManager, DialogueManagerClient]: Dialogue manager instance
                or client stub for remote calls.
        """
        pass

    @abstractmethod
    async def reload(self) -> None:
        """
        Reload the dialogue manager with fresh data and models.
        
        Useful after training completion or configuration changes.
        """
        pass


class LocalDialogueManagerProvider(DialogueManagerProvider):
    """
    Provider for in-process DialogueManager instances.
    
    Manages the lifecycle of a local DialogueManager instance with
    initialization and reload capabilities. Suitable for monolith deployments.
    """

    def __init__(self):
        """Initialize the local provider with no instance."""
        self._instance: Optional[DialogueManager] = None

    async def get(self) -> DialogueManager:
        """
        Get the local dialogue manager instance.
        
        Initializes on first call if not already initialized.
        
        Returns:
            DialogueManager: The initialized dialogue manager instance
        """
        if self._instance is None:
            await self._initialize()
        return self._instance

    async def _initialize(self) -> None:
        """
        Initialize the dialogue manager with configuration.
        
        Loads configuration, initializes the DialogueManager, and updates
        with trained models from the configured models directory.
        """
        logger.info("Initializing local dialogue manager")
        settings = get_settings()
        self._instance = await DialogueManager.from_config()
        self._instance.update_model(settings.MODELS_DIR)
        logger.info("Local dialogue manager initialized")

    async def reload(self) -> None:
        """
        Reload the dialogue manager with new data and models.
        
        Recreates the dialogue manager with fresh data and reloads trained models.
        Useful after training completion.
        """
        logger.info("Reloading local dialogue manager")
        settings = get_settings()

        # Recreate dialogue manager with new data
        new_instance = await DialogueManager.from_config()

        # Update dialogue manager with new models
        new_instance.update_model(settings.MODELS_DIR)

        self._instance = new_instance
        logger.info("Local dialogue manager reloaded")


class DialogueManagerClient:
    """
    HTTP client stub for remote dialogue manager microservice.
    
    Provides a client interface that forwards calls to a remote dialogue-manager
    microservice. This class is a placeholder for future implementation when
    the dialogue manager is deployed as a separate microservice.
    
    Long-term: Replace with actual HTTP client implementation that calls
    the dialogue-manager service endpoints.
    """

    def __init__(self, service_url: str):
        """
        Initialize the dialogue manager client.
        
        Args:
            service_url: Base URL of the remote dialogue-manager service
        """
        self.service_url = service_url
        logger.info(f"Initialized dialogue manager client for {service_url}")

    async def process(self, message):
        """
        Forward message processing to remote service.
        
        Args:
            message: UserMessage instance
            
        Returns:
            State: Response from remote service
        """
        # TODO: Implement HTTP call to remote service
        # POST {service_url}/process with message payload
        raise NotImplementedError(
            "Remote dialogue manager client not yet implemented. "
            "Deploy dialogue-manager as standalone microservice."
        )


class RemoteDialogueManagerProvider(DialogueManagerProvider):
    """
    Provider for remote DialogueManager microservice clients.
    
    Creates HTTP client stubs that forward calls to a remote dialogue-manager
    microservice. Suitable for split microservice deployments.
    
    Long-term: Implement actual HTTP communication when dialogue-manager
    is deployed as a separate service.
    """

    def __init__(self, service_url: str):
        """
        Initialize the remote provider.
        
        Args:
            service_url: Base URL of the remote dialogue-manager service
        """
        self.service_url = service_url
        self._client: Optional[DialogueManagerClient] = None

    async def get(self) -> DialogueManagerClient:
        """
        Get a client for the remote dialogue manager service.
        
        Returns:
            DialogueManagerClient: Client stub for remote calls
        """
        if self._client is None:
            self._client = DialogueManagerClient(self.service_url)
        return self._client

    async def reload(self) -> None:
        """
        Signal the remote service to reload its models.
        
        TODO: Implement HTTP call to remote service reload endpoint.
        """
        logger.info(f"Signaling reload to remote dialogue manager at {self.service_url}")
        # TODO: POST {service_url}/reload


# Global provider instance - initialized based on deployment configuration
_provider: Optional[DialogueManagerProvider] = None


def _get_provider() -> DialogueManagerProvider:
    """
    Get the global dialogue manager provider.
    
    Lazily initializes the provider based on configuration.
    For monolith deployments, uses LocalDialogueManagerProvider.
    For microservice deployments, uses RemoteDialogueManagerProvider.
    
    Returns:
        DialogueManagerProvider: The configured provider instance
    """
    global _provider
    if _provider is None:
        settings = get_settings()
        
        # Check for remote service configuration
        dialogue_manager_service_url = getattr(
            settings, "DIALOGUE_MANAGER_SERVICE_URL", None
        )
        
        if dialogue_manager_service_url:
            logger.info(
                f"Using remote dialogue manager provider: {dialogue_manager_service_url}"
            )
            _provider = RemoteDialogueManagerProvider(dialogue_manager_service_url)
        else:
            logger.info("Using local dialogue manager provider")
            _provider = LocalDialogueManagerProvider()
    
    return _provider


async def get_dialogue_manager() -> Union[DialogueManager, DialogueManagerClient]:
    """
    Get a dialogue manager instance or client.
    
    This is the primary dependency injection function for API layers.
    Returns either a local DialogueManager instance (monolith) or a
    DialogueManagerClient stub (microservice deployment).
    
    Returns:
        Union[DialogueManager, DialogueManagerClient]: Dialogue manager instance
            or client stub depending on deployment configuration
    """
    provider = _get_provider()
    return await provider.get()


async def init_dialogue_manager() -> None:
    """
    Initialize the dialogue manager provider.
    
    For local deployments, initializes the DialogueManager instance.
    For remote deployments, verifies connectivity to the service.
    
    Should be called during application startup.
    """
    provider = _get_provider()
    logger.info("Initializing dialogue manager provider")
    
    # For local provider, this triggers initialization
    if isinstance(provider, LocalDialogueManagerProvider):
        await provider.get()
    
    logger.info("Dialogue manager provider initialized")


async def reload_dialogue_manager() -> None:
    """
    Reload the dialogue manager with new data and models.
    
    Delegates to the configured provider's reload method.
    Useful after training completion or configuration changes.
    """
    provider = _get_provider()
    logger.info("Reloading dialogue manager")
    await provider.reload()
    logger.info("Dialogue manager reloaded")


def set_provider(provider: DialogueManagerProvider) -> None:
    """
    Set a custom dialogue manager provider.
    
    Useful for testing or custom deployment scenarios.
    
    Args:
        provider: DialogueManagerProvider instance to use
    """
    global _provider
    _provider = provider
    logger.info(f"Set custom dialogue manager provider: {type(provider).__name__}")