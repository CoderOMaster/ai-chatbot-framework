from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import Field
from pydantic_settings import BaseSettings

from app.bot.channels.facebook.messenger import FacebookReceiver
from app.bot.dialogue_manager.http_client import APICallException, call_api
from app.dependencies import DialogueManagerClient

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)

DEFAULT_INTEGRATIONS_TIMEOUT = 30.0
DEFAULT_INTEGRATIONS_ENDPOINT_TEMPLATE = "/integrations/{integration_name}"
DEFAULT_DIALOGUE_MANAGER_TIMEOUT = 30.0
DEFAULT_DIALOGUE_MANAGER_PROCESS_ENDPOINT = "/dialogue/process"
DEFAULT_DIALOGUE_MANAGER_RELOAD_ENDPOINT = "/dialogue/reload"


class IntegrationsServiceConfig(BaseSettings):
    """Configuration for interacting with the integrations service."""

    service_url: str = Field(..., env="INTEGRATIONS_SERVICE_URL")
    timeout_seconds: float = Field(DEFAULT_INTEGRATIONS_TIMEOUT, env="INTEGRATIONS_SERVICE_TIMEOUT")
    endpoint_template: str = Field(
        DEFAULT_INTEGRATIONS_ENDPOINT_TEMPLATE,
        env="INTEGRATIONS_SERVICE_ENDPOINT_TEMPLATE",
    )

    class Config:
        case_sensitive = False


class IntegrationRepository:
    """Repository that retrieves integration metadata from a remote service."""

    def __init__(self, config: IntegrationsServiceConfig) -> None:
        self._config = config

    def _build_url(self, integration_name: str) -> str:
        trimmed_path = self._config.endpoint_template.format(integration_name=integration_name).lstrip("/")
        return f"{self._config.service_url.rstrip('/')}/{trimmed_path}"

    async def fetch_integration_settings(self, integration_name: str) -> Dict[str, Any]:
        """Return the integration settings payload for the requested integration."""

        url = self._build_url(integration_name)
        try:
            response = await call_api(url, "GET", timeout=self._config.timeout_seconds)
        except APICallException as exc:
            logger.error("Integrations service request failed for %s: %s", integration_name, exc)
            raise HTTPException(
                status_code=502,
                detail="Unable to reach the integrations service to validate Facebook configuration",
            ) from exc

        payload = response.body
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Received unexpected payload from integrations service")

        if payload.get("status") is False:
            raise HTTPException(status_code=404, detail=f"{integration_name.title()} integration is disabled")

        settings = payload.get("settings")
        if not isinstance(settings, dict):
            nested = payload.get("integration")
            if isinstance(nested, dict):
                settings = nested.get("settings")
        if not isinstance(settings, dict):
            raise HTTPException(status_code=502, detail="Integrations service did not return valid settings")

        return settings


@lru_cache()
def _load_integrations_service_config() -> IntegrationsServiceConfig:
    return IntegrationsServiceConfig()


async def get_integration_repository() -> IntegrationRepository:
    """Return an injected repository for fetching integration configurations."""

    return IntegrationRepository(_load_integrations_service_config())


async def get_facebook_config(
    repository: IntegrationRepository = Depends(get_integration_repository),
) -> Dict[str, Any]:
    """Fetch the Facebook integration configuration from the integrations service."""

    return await repository.fetch_integration_settings("facebook")


@router.get("/webhook")
async def verify_webhook(
    request: Request, config: Dict[str, Any] = Depends(get_facebook_config)
) -> int:
    """Handle Facebook webhook verification requests."""

    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if hub_mode and token:
        if hub_mode == "subscribe" and token == config["verify"]:
            return int(challenge)
        raise HTTPException(status_code=403, detail="Invalid verification token")

    raise HTTPException(status_code=400, detail="Invalid request parameters")


async def get_remote_dialogue_manager_client() -> DialogueManagerClient:
    """Instantiate a dialogue-manager-service client for Lambda deployments."""

    service_url = os.environ.get("DIALOGUE_MANAGER_SERVICE_URL")
    if not service_url:
        raise RuntimeError("DIALOGUE_MANAGER_SERVICE_URL must be configured to reach the dialogue-manager-service")

    process_endpoint = os.environ.get(
        "DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT", DEFAULT_DIALOGUE_MANAGER_PROCESS_ENDPOINT
    )
    reload_endpoint = os.environ.get(
        "DIALOGUE_MANAGER_SERVICE_RELOAD_ENDPOINT", DEFAULT_DIALOGUE_MANAGER_RELOAD_ENDPOINT
    )
    timeout = _parse_timeout(os.environ.get("DIALOGUE_MANAGER_SERVICE_TIMEOUT"), DEFAULT_DIALOGUE_MANAGER_TIMEOUT)

    return DialogueManagerClient(service_url, process_endpoint, reload_endpoint, timeout)


def _parse_timeout(value: Optional[str], default: float) -> float:
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


@router.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    config: Dict[str, Any] = Depends(get_facebook_config),
    dialogue_manager_client: DialogueManagerClient = Depends(get_remote_dialogue_manager_client),
) -> Dict[str, bool]:
    """Process Facebook webhook events by delegating to the remote dialogue manager client."""

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature", "")

    facebook = FacebookReceiver(config, dialogue_manager_client)

    if not facebook.validate_hub_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        data = await request.json()
        background_tasks.add_task(facebook.process_webhook_event, data)
        return {"success": True}
    except Exception as exc:
        logger.error("Error processing webhook: %s", exc)
        raise HTTPException(status_code=500, detail="Error processing webhook")