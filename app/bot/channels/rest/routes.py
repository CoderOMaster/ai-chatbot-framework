from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager, DialogueManagerClient

router = APIRouter(prefix="/rest", tags=["rest"])


class RestWebhookRequest(BaseModel):
    """Pydantic model for the REST webhook request.

    Attributes:
        thread_id: Identifier of the conversation/thread.
        text: The user message text.
        context: Optional chat context dictionary.
    """

    thread_id: str
    text: str
    context: Optional[Dict[str, Any]] = None


@router.post("/webhook")
async def webhook(body: RestWebhookRequest, dialogue_manager: Any = Depends(get_dialogue_manager)):
    """Receive a message from REST channels and forward it to the dialogue-manager service.

    This route accepts a structured request (RestWebhookRequest), converts it to the
    shared UserMessage DTO and forwards it to either an in-process DialogueManager
    (monolith deployments) or a remote dialogue-manager-service via the
    DialogueManagerClient.

    Returns the bot_message portion of the resulting conversation state.
    """

    user_message = UserMessage(thread_id=body.thread_id, text=body.text, context=body.context or {})

    if dialogue_manager is None:
        # No manager available (split-deployment misconfiguration)
        raise HTTPException(status_code=503, detail="Dialogue manager service unavailable")

    try:
        # Support both in-process DialogueManager (has .process) and remote client
        if hasattr(dialogue_manager, "process") and callable(getattr(dialogue_manager, "process")):
            # In-process manager returns a State-like object
            new_state = await dialogue_manager.process(user_message)
        elif isinstance(dialogue_manager, DialogueManagerClient):
            # Remote client: forward the serialized UserMessage to the remote service
            # The remote service is expected to expose a "process" endpoint that
            # accepts the UserMessage representation and returns a JSON state.
            response = await dialogue_manager.request("POST", "/process", json=user_message.to_dict())
            # The client.request helper may return the decoded JSON body directly
            new_state = response
        else:
            # Unknown manager type
            raise HTTPException(status_code=500, detail="Unsupported dialogue manager implementation")

    except HTTPException:
        raise
    except Exception as e:
        # Translate unknown errors into a 502 Bad Gateway to indicate an upstream failure
        raise HTTPException(status_code=502, detail=str(e))

    # Extract bot_message from either the State object or the returned dict
    if hasattr(new_state, "bot_message"):
        return new_state.bot_message
    if isinstance(new_state, dict):
        return new_state.get("bot_message")

    # Fallback: return the full response if no bot_message found
    return new_state