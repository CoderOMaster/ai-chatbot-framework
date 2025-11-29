from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import (
    DialogueManagerClient,
    DialogueManagerClientException,
    get_dialogue_manager,
)

router = APIRouter(prefix="/test", tags=["test"])


async def get_dialogue_manager_service_client(
    manager: object = Depends(get_dialogue_manager),
) -> DialogueManagerClient:
    """Ensure the endpoint always operates against the remote dialogue manager service."""

    if not isinstance(manager, DialogueManagerClient):
        raise HTTPException(
            status_code=500,
            detail="This endpoint requires the dialogue-manager-service to be configured.",
        )
    return manager


@router.post("/chat")
async def chat(
    body: dict[str, Any],
    dialogue_manager_client: DialogueManagerClient = Depends(
        get_dialogue_manager_service_client
    ),
) -> dict[str, Any]:
    """Proxy a diagnostic user message to the dialogue-manager-service and return the state."""

    user_message = UserMessage(
        thread_id=body["thread_id"],
        text=body["text"],
        context=body.get("context", {}),
    )
    try:
        new_state = await dialogue_manager_client.process(user_message)
    except DialogueManagerClientException as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return new_state.to_dict()