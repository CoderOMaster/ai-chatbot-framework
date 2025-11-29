from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from app.bot.dialogue_manager.http_client import APICallException, call_api
from app.bot.dialogue_manager.models import UserMessage
from app.bot.memory.models import State

router = APIRouter(prefix="/rest", tags=["rest"])


class DialogueManagerServiceSettings(BaseSettings):
    """Configuration for calling the dialogue-manager microservice."""

    service_url: str = Field(..., env="DIALOGUE_MANAGER_SERVICE_URL")
    process_endpoint: str = Field(
        "/dialogue/process",
        env="DIALOGUE_MANAGER_SERVICE_PROCESS_ENDPOINT",
    )
    timeout: float = Field(30.0, env="DIALOGUE_MANAGER_SERVICE_TIMEOUT")


class DialogueManagerServiceClientError(Exception):
    """Raised when the dialogue-manager-service client cannot process a request."""


class DialogueManagerServiceClient:
    """Thin HTTP client that forwards dialogue requests to the service."""

    def __init__(self, settings: DialogueManagerServiceSettings) -> None:
        self._base_url = settings.service_url.rstrip("/")
        self._process_endpoint = settings.process_endpoint
        self._timeout = settings.timeout

    def _build_url(self, endpoint: str) -> str:
        trimmed = endpoint.lstrip("/")
        return f"{self._base_url}/{trimmed}"

    async def process(self, message: UserMessage) -> State:
        """Serialize the user message, forward it to the remote service, and return the updated state."""

        payload = message.to_dict()
        url = self._build_url(self._process_endpoint)
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
            raise DialogueManagerServiceClientError(
                "Unable to reach the dialogue-manager-service"
            ) from exc

        body = response.body
        if not isinstance(body, dict):
            raise DialogueManagerServiceClientError(
                "Dialogue manager service returned an unexpected payload"
            )
        try:
            return State.from_dict(body)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise DialogueManagerServiceClientError(
                "Dialogue manager service returned an invalid state"
            ) from exc


@lru_cache(maxsize=1)
def get_dialogue_manager_service_settings() -> DialogueManagerServiceSettings:
    """Lazily instantiate the settings that describe the dialogue-manager-service endpoints."""

    return DialogueManagerServiceSettings()


def get_dialogue_manager_service_client(
    settings: DialogueManagerServiceSettings = Depends(get_dialogue_manager_service_settings),
) -> DialogueManagerServiceClient:
    """Create a client configured with the current dialogue-manager-service metadata."""

    return DialogueManagerServiceClient(settings=settings)


class RestWebhookRequest(BaseModel):
    """Represents the expected payload from the REST webhook channel."""

    thread_id: str
    text: str
    context: Dict[str, Any] = Field(default_factory=dict)


async def process_rest_webhook_request(
    request: RestWebhookRequest,
    dialogue_manager_client: DialogueManagerServiceClient,
) -> List[Dict[str, Any]]:
    """Handle the business logic for a REST webhook webhook invocation."""

    user_message = UserMessage(
        thread_id=request.thread_id,
        text=request.text,
        context=request.context,
    )
    state = await dialogue_manager_client.process(user_message)
    return state.bot_message or []


@router.post("/webbook")
async def webbook(
    body: RestWebhookRequest,
    dialogue_manager_client: DialogueManagerServiceClient = Depends(
        get_dialogue_manager_service_client
    ),
) -> List[Dict[str, Any]]:
    """Endpoint to converse with the chatbot via REST channels."""

    try:
        return await process_rest_webhook_request(body, dialogue_manager_client)
    except DialogueManagerServiceClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc