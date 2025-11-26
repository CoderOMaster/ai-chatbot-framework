from typing import Optional, Any
import logging
import os

import aiohttp

try:
    from app.config import app_config
except Exception:
    # app_config may not be present in split deployments; fall back to env vars
    app_config = None

logger = logging.getLogger(__name__)

# In the monolith this will hold a real DialogueManager instance.
# In a split deployment this module acts as a factory for DialogueManagerClient
# and no global heavy-weight object is kept unless explicitly initialized.
_dialogue_manager: Optional[Any] = None


class DialogueManagerClient:
    """Thin HTTP client for the dialogue-manager-service.

    This client provides a minimal compatibility layer for code that expects
    a dialogue manager-like object. It forwards simple operations to the
    remote service over HTTP. Add methods as needed to match the local
    DialogueManager API used by the rest of the application.
    """

    def __init__(self, base_url: str, session: Optional[aiohttp.ClientSession] = None):
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = False

    async def _session_or_create(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def request(self, method: str, path: str, **kwargs) -> Any:
        """Perform a JSON HTTP request to the dialogue-manager-service."""
        session = await self._session_or_create()
        url = f"{self.base_url}/{path.lstrip('/') }"
        async with session.request(method, url, **kwargs) as resp:
            resp.raise_for_status()
            # try to decode json, fall back to raw text
            try:
                return await resp.json()
            except Exception:
                return await resp.text()

    async def update_model(self, models_dir: str) -> Any:
        """Request the remote service to update its models.

        Returns the decoded JSON response from the service.
        """
        payload = {"models_dir": models_dir}
        return await self.request("POST", "/update-model", json=payload)

    async def reload(self) -> Any:
        """Ask the remote service to reload its state/data."""
        return await self.request("POST", "/reload")

    async def close(self) -> None:
        """Close the underlying HTTP session if owned by this client."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None


async def get_dialogue_manager(base_url: Optional[str] = None) -> Optional[Any]:
    """Return the in-process DialogueManager if initialized, otherwise
    return a DialogueManagerClient pointing at the dialogue-manager-service.

    If a global in-process manager has been set (monolith mode) it will be
    returned. In a split deployment this returns a new DialogueManagerClient
    constructed from `base_url`, the app config, or the DIALOGUE_MANAGER_URL
    environment variable.
    """
    global _dialogue_manager

    # If the monolith initialized a local manager, prefer that
    if _dialogue_manager is not None:
        return _dialogue_manager

    # Determine service URL from argument, config or environment
    service_url = base_url
    if service_url is None:
        if app_config is not None and hasattr(app_config, "DIALOGUE_MANAGER_URL"):
            service_url = getattr(app_config, "DIALOGUE_MANAGER_URL")
        else:
            service_url = os.getenv("DIALOGUE_MANAGER_URL")

    if service_url:
        return DialogueManagerClient(service_url)

    # No manager available
    return None


async def set_dialogue_manager(dialogue_manager: Any) -> None:
    """Set the global in-process DialogueManager instance (monolith only).

    Prefer using dependency injection / client factories in split deployments.
    """
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def init_dialogue_manager() -> None:
    """Startup hook for monolith deployments.

    Attempts to import and construct the in-process DialogueManager. If the
    local DialogueManager implementation is not present (split deployment),
    this function will log and no in-process manager will be created.
    """
    global _dialogue_manager
    logger.info("initializing dialogue manager")

    try:
        # Import lazily to avoid importing heavy runtime in split deployments
        from app.bot.dialogue_manager.dialogue_manager import DialogueManager  # type: ignore

        _dialogue_manager = await DialogueManager.from_config()

        # Determine models dir from config if available
        models_dir = None
        if app_config is not None and hasattr(app_config, "MODELS_DIR"):
            models_dir = getattr(app_config, "MODELS_DIR")
        elif os.getenv("MODELS_DIR"):
            models_dir = os.getenv("MODELS_DIR")

        if models_dir and hasattr(_dialogue_manager, "update_model"):
            _dialogue_manager.update_model(models_dir)

        logger.info("dialogue manager initialized")
    except Exception:
        logger.exception(
            "Could not initialize in-process DialogueManager; assuming split deployment and using remote client"
        )


async def reload_dialogue_manager() -> None:
    """Reload the global in-process DialogueManager (monolith only).

    For split deployments the remote service should be asked to reload via
    the DialogueManagerClient instead.
    """
    global _dialogue_manager

    try:
        from app.bot.dialogue_manager.dialogue_manager import DialogueManager  # type: ignore

        # recreate dialogue manager with new data
        dialogue_manager = await DialogueManager.from_config()

        # update dialogue manager with new models
        models_dir = None
        if app_config is not None and hasattr(app_config, "MODELS_DIR"):
            models_dir = getattr(app_config, "MODELS_DIR")
        elif os.getenv("MODELS_DIR"):
            models_dir = os.getenv("MODELS_DIR")

        if models_dir and hasattr(dialogue_manager, "update_model"):
            dialogue_manager.update_model(models_dir)

        await set_dialogue_manager(dialogue_manager)

        logger.info("dialogue manager reloaded")
    except Exception:
        logger.exception("Could not reload in-process DialogueManager")