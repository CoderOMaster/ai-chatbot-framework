from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx

from shared.models.dialogue import UserMessage

router = APIRouter(prefix="/rest", tags=["rest"])


class WebhookRequest(BaseModel):
    """Request model for webhook endpoint validation."""
    thread_id: str = Field(..., description="Unique thread identifier")
    text: str = Field(..., description="User message text")
    context: dict = Field(default_factory=dict, description="Optional context data")


@router.post("/webhook")
async def webhook(request: WebhookRequest) -> dict:
    """
    Endpoint to converse with the chatbot.
    Delegates the request processing to DialogueManager service.

    Args:
        request: Validated webhook request containing thread_id, text, and context

    Returns:
        JSON response with the chatbot's reply and context.
    """
    user_message = UserMessage(
        thread_id=request.thread_id,
        text=request.text,
        context=request.context
    )
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://dialogue-manager-service/process",
                json=user_message.dict()
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")