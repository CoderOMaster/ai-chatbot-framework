from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import httpx

from app.bot.dialogue_manager.models import UserMessage

router = APIRouter(prefix="/rest", tags=["rest"])


class WebhookRequest(BaseModel):
    """Request model for the REST webhook endpoint.
    
    Represents a user message sent to the chatbot via the REST channel.
    """
    thread_id: str = Field(..., description="Unique identifier for the conversation thread")
    text: str = Field(..., description="User's message text")
    context: Dict[str, Any] = Field(default_factory=dict, description="Dialogue context")


class DialogueManagerClient:
    """HTTP client for communicating with the dialogue-manager service.
    
    Handles forwarding user messages to the dialogue manager and retrieving responses.
    """
    
    def __init__(self, base_url: str = "http://dialogue-manager:8000"):
        """Initialize the dialogue manager client.
        
        Args:
            base_url: Base URL of the dialogue-manager service
        """
        self.base_url = base_url
    
    async def process_message(self, user_message: UserMessage) -> Dict[str, Any]:
        """Send a user message to the dialogue manager for processing.
        
        Args:
            user_message: The user message to process
            
        Returns:
            Dictionary containing the bot's response and updated state
            
        Raises:
            HTTPException: If the dialogue manager returns an error
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/process",
                    json=user_message.to_dict(),
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Dialogue manager error: {e.response.text}"
                )
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to reach dialogue manager service: {str(e)}"
                )


# Initialize the dialogue manager client
dialogue_manager_client = DialogueManagerClient()


@router.post("/webbook")
async def webbook(request: WebhookRequest) -> Dict[str, Any]:
    """Endpoint to converse with the chatbot.
    
    Receives a user message via REST and forwards it to the dialogue-manager service
    for processing. Returns the chatbot's reply and updated context.
    
    Args:
        request: The webhook request containing thread_id, text, and context
        
    Returns:
        JSON response with the chatbot's reply and context
        
    Raises:
        HTTPException: If message processing fails
    """
    user_message = UserMessage(
        thread_id=request.thread_id,
        text=request.text,
        context=request.context,
        channel="rest"
    )
    
    try:
        response = await dialogue_manager_client.process_message(user_message)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error processing message: {str(e)}"
        )