from __future__ import annotations

import logging
import os
from typing import Any, Optional, Union

from app.bot.dialogue_manager.http_client import APICallException, call_api
from app.bot.dialogue_manager.models import UserMessage
from app.bot.memory.models import State
from app.config import app_config

logger = logging.getLogger(__name__)

DEFAULT_DIALOGUE_MANAGER_TIMEOUT = 30.0

def _parse_timeout(value: Optional[str], default: float = DEFAULT_DIALOGUE_MANAGER_TIMEOUT) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(
            "Invalid DIALOGUE_MANAGER_SERVICE_TIMEOUT=%s, falling back to %.1f seconds",
            value,
            default,
        )
        return default


_DIALOGUE_MANAGER_SERVICE_URL = os.environ.get("DIALOGUE_MANAGER_SERVICE_URL")
_DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT = os.environ.get(
    "DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT", "/dialogue/process"
)
_DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT = os.environ.get(
    "DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT", "/dialogue/reload"
)
_DIALOGUE_MANAGER_SERVICE_TIMEOUT = _parse_timeout(
    os.environ.get("DIALOGUE_MANAGER_SERVICE_TIMEOUT")
)
_REMOTE_DIALOGUE_MANAGER_ENABLED = bool(_DIALOGUE_MANAGER_SERVICE_URL)

if _REMOTE_DIALOGUE_MANAGER_ENABLED:
    logger.info(
        "Configured to proxy requests to the dialogue-manager-service at %s",
        _DIALOGUE_MANAGER_SERVICE_URL,
    )


_dialogue_manager: Optional["DialogueManager"] = None


class DialogueManagerClientException(Exception):
    """Raised when the dialogue-manager-service client fails to complete a request."""


class DialogueManagerClient:
    """Thin HTTP client that forwards dialogue requests to the dialogue-manager-service."""

    def __init__(
        self,
        base_url: str,
        process_endpoint: str,
        reload_endpoint: str,
        timeout: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._process_endpoint = process_endpoint
        self._reload_endpoint = reload_endpoint
        self._timeout = timeout

    def _build_url(self, endpoint: str) -> str:
        trimmed = endpoint.lstrip("/")
        return f"{self._base_url}/{trimmed}"

    async def _post(
        self, endpoint: str, payload: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        url = self._build_url(endpoint)
        try:
            response = await call_api(
                url,
                "POST",
                headers={"Content-Type": "application/json"},
                parameters=payload,
                is_json=True,
                timeout=self._timeout,
            )
        except APICallException as exc:
            logger.error("Dialogue manager service %s failed: %s", url, exc)
            raise DialogueManagerClientException(
                "Unable to reach the dialogue-manager-service"
            ) from exc

        body = response.body
        if not isinstance(body, dict):
            raise DialogueManagerClientException("Unexpected response from dialogue manager service")
        return body

    async def process(self, message: UserMessage) -> State:
        """Serialize a user message, forward it to the service, and return the updated state."""
        payload = message.to_dict()
        response_payload = await self._post(self._process_endpoint, payload=payload)
        return State.from_dict(response_payload)

    async def reload(self) -> None:
        """Request that the remote dialogue manager reload its models."""
        await self._post(self._reload_endpoint)


DialogueManagerDependency = Union["DialogueManager", DialogueManagerClient]


def _build_remote_client() -> DialogueManagerClient:
    if not _DIALOGUE_MANAGER_SERVICE_URL:
        raise RuntimeError("Remote dialogue manager service is not configured")
    return DialogueManagerClient(
        base_url=_DIALOGUE_MANAGER_SERVICE_URL,
        process_endpoint=_DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT,
        reload_endpoint=_DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT,
        timeout=_DIALOGUE_MANAGER_SERVICE_TIMEOUT,
    )


async def get_dialogue_manager() -> DialogueManagerDependency:
    """FastAPI dependency that returns the configured dialogue manager implementation."""
    if _REMOTE_DIALOGUE_MANAGER_ENABLED:
        return _build_remote_client()
    if _dialogue_manager is None:
        raise RuntimeError("Dialogue manager has not been initialized. Did you call init_dialogue_manager()?")
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: "DialogueManager") -> None:
    """Update the internal dialogue manager reference for the monolith deployments."""
    if _REMOTE_DIALOGUE_MANAGER_ENABLED:
        raise RuntimeError("Cannot replace the dialogue manager when the remote service is enabled")
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def init_dialogue_manager() -> None:
    """Initialize the local dialogue manager when the service is running in monolith mode."""
    if _REMOTE_DIALOGUE_MANAGER_ENABLED:
        logger.info(
            "Skipping local dialogue manager initialization because remote service is configured"
        )
        return
    logger.info("initializing dialogue manager")
    from app.bot.dialogue_manager.dialogue_manager import DialogueManager

    global _dialogue_manager
    _dialogue_manager = await DialogueManager.from_config()
    _dialogue_manager.update_model(app_config.MODELS_DIR)
    logger.info("dialogue manager initialized")


async def reload_dialogue_manager() -> None:
    """Reload the dialogue manager models for monolith deployments or delegate to the remote service."""
    if _REMOTE_DIALOGUE_MANAGER_ENABLED:
        logger.info("Requesting remote dialogue manager to reload models")
        client = _build_remote_client()
        await client.reload()
        logger.info("Remote dialogue manager reload requested")
        return

    from app.bot.dialogue_manager.dialogue_manager import DialogueManager

    dialogue_manager = await DialogueManager.from_config()
    dialogue_manager.update_model(app_config.MODELS_DIR)
    await set_dialogue_manager(dialogue_manager)
    logger.info("dialogue manager reloaded")