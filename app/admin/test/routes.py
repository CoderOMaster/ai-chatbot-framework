from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from typing import Dict, Any, Union

from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager, DialogueManagerClient
from app.bot.dialogue_manager.dialogue_manager import (
    DialogueManager,
    DialogueManagerException,
)

router = APIRouter(prefix="/test", tags=["test"])


class ChatRequest(BaseModel):
    """Validated request model for chat endpoint.
    
    Ensures thread_id, text, and context are provided and properly typed.
    """
    thread_id: str = Field(..., min_length=1, description="Unique conversation thread identifier")
    text: str = Field(..., min_length=1, description="User message text")
    context: Dict[str, Any] = Field(default_factory=dict, description="Dialogue context")
    
    @validator('thread_id')
    def validate_thread_id(cls, v):
        """Validate thread_id is non-empty string."""
        if not v or not isinstance(v, str):
            raise ValueError("thread_id must be a non-empty string")
        return v.strip()
    
    @validator('text')
    def validate_text(cls, v):
        """Validate text is non-empty string."""
        if not v or not isinstance(v, str):
            raise ValueError("text must be a non-empty string")
        return v.strip()
    
    @validator('context')
    def validate_context(cls, v):
        """Validate context is a dictionary."""
        if not isinstance(v, dict):
            raise ValueError("context must be a dictionary")
        return v


@router.post("/chat")
async def chat(
    body: ChatRequest,
    dialogue_manager: Union[DialogueManager, DialogueManagerClient] = Depends(get_dialogue_manager)
) -> Dict[str, Any]:
    """
    Endpoint to converse with the chatbot.
    
    Delegates the request processing to DialogueManager (local) or DialogueManagerClient (remote).
    Validates input fields (thread_id, text, context) before processing.

    Args:
        body: Validated chat request with thread_id, text, and context
        dialogue_manager: Injected dialogue manager instance or remote client
        
    Returns:
        JSON response with the chatbot's reply and context.
        
    Raises:
        HTTPException: If dialogue manager processing fails or input validation fails
    """
    
    user_message = UserMessage(
        thread_id=body.thread_id,
        text=body.text,
        context=body.context
    )
    
    try:
        new_state = await dialogue_manager.process(user_message)
    except DialogueManagerException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        # Handle remote client not yet implemented
        raise HTTPException(status_code=503, detail="Dialogue manager service unavailable")
    except Exception as e:
        # Catch unexpected errors
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
    
    return new_state.to_dict()