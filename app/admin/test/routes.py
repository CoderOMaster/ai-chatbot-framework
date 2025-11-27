from typing import Any, Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager
from app.bot.dialogue_manager.dialogue_manager import DialogueManagerException


router = APIRouter(prefix="/test", tags=["test"])


class DialogueProcessor(Protocol):
    """Protocol describing the minimal interface the handler expects from a dialogue manager."""

    async def process(self, message: UserMessage) -> Any:  # pragma: no cover - simple protocol
        ...


class ChatRequest(BaseModel):
    """Request body schema for the /test/chat endpoint.

    Using a Pydantic model ensures automatic validation of required fields.
    """

    thread_id: str = Field(..., alias="thread_id")
    text: str
    context: Optional[dict] = None


@router.post("/chat")
async def chat(
    body: ChatRequest, dialogue_manager: Optional[DialogueProcessor] = Depends(get_dialogue_manager)
) -> Any:
    """Endpoint to converse with the chatbot.

    Validates the incoming payload using ChatRequest and converts it to the
    internal UserMessage value object via its factory constructor. Handles a
    possibly-uninitialized dialogue manager and converts DialogueManager
    exceptions into structured 4xx HTTP responses.
    """

    if dialogue_manager is None:
        # Dialogue manager failed to initialize; surface a clear service-unavailable error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "dialogue_manager_unavailable", "message": "Dialogue manager is not initialized"},
        )

    # Build a UserMessage via the provided factory to keep validation in one place
    try:
        user_message = UserMessage.from_dict(
            {
                "thread_id": body.thread_id,
                "text": body.text,
                "context": body.context or {},
            }
        )
    except KeyError as e:
        # Defensive: if factory raises due to missing keys, return structured validation error
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_payload", "message": f"Missing key: {e.args[0]}"},
        )

    try:
        new_state = await dialogue_manager.process(user_message)
    except DialogueManagerException as e:
        # Map dialogue manager domain errors to a consistent 4xx payload
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "dialogue_manager_error", "message": str(e)},
        )
    except Exception:
        # Unexpected errors should be returned as 500 without leaking internals
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "message": "An unexpected error occurred"},
        )

    # Preserve original contract: return a dict if the state exposes to_dict(), otherwise return raw
    to_dict = getattr(new_state, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return new_state