import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field, validator
import httpx
from app.bot.dialogue_manager.models import UserMessage
from app.bot.dialogue_manager.dialogue_manager import DialogueManagerException

router = APIRouter(prefix="/rest", tags=["rest"])


class WebhookRequest(BaseModel):
    """Validated webhook request model."""
    thread_id: str = Field(..., min_length=1, description="Thread ID for conversation tracking")
    text: str = Field(..., min_length=1, max_length=5000, description="User message text")
    context: Optional[dict] = Field(default=None, description="Optional context data")
    
    @validator('thread_id')
    def validate_thread_id(cls, v):
        """Validate thread_id format."""
        if not v.strip():
            raise ValueError("thread_id cannot be empty")
        return v.strip()
    
    @validator('text')
    def validate_text(cls, v):
        """Validate text content."""
        if not v.strip():
            raise ValueError("text cannot be empty")
        return v.strip()


class WebhookResponse(BaseModel):
    """Webhook response model."""
    request_id: str = Field(..., description="Unique request identifier for tracking")
    bot_message: str = Field(..., description="Bot's response message")
    context: Optional[dict] = Field(default=None, description="Response context")


# Simple in-memory rate limiter (for Lambda, consider external service for distributed rate limiting)
_request_counts = {}
MAX_REQUESTS_PER_MINUTE = 60


def _check_rate_limit(client_id: str) -> bool:
    """Check if client has exceeded rate limit."""
    import time
    current_minute = int(time.time() / 60)
    key = f"{client_id}:{current_minute}"
    
    _request_counts[key] = _request_counts.get(key, 0) + 1
    
    # Cleanup old entries
    if len(_request_counts) > 10000:
        _request_counts.clear()
    
    return _request_counts[key] <= MAX_REQUESTS_PER_MINUTE


async def _call_dialogue_manager_service(
    user_message: UserMessage,
    request_id: str,
    dialogue_manager_url: str = "http://localhost:8001"
) -> dict:
    """
    Call dialogue-manager service via HTTP.
    
    Args:
        user_message: The user message to process
        request_id: Unique request identifier for tracking
        dialogue_manager_url: Base URL of dialogue-manager service
        
    Returns:
        Response from dialogue-manager service
        
    Raises:
        HTTPException: If service call fails
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{dialogue_manager_url}/process",
                json={
                    "thread_id": user_message.thread_id,
                    "text": user_message.text,
                    "context": user_message.context,
                },
                headers={"X-Request-ID": request_id},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Dialogue manager service unavailable: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error communicating with dialogue manager: {str(e)}"
        )


@router.post("/webhook", response_model=WebhookResponse)
async def webhook(
    request: Request,
    body: WebhookRequest,
    x_request_id: Optional[str] = Header(None),
) -> WebhookResponse:
    """
    REST endpoint to converse with the chatbot.
    
    Processes user messages with request validation, rate limiting, and request tracking.
    For long-running dialogues, returns immediately with request_id for async polling.
    
    Args:
        request: FastAPI request object
        body: Validated webhook request
        x_request_id: Optional request ID from header
        
    Returns:
        WebhookResponse with bot message and tracking ID
        
    Raises:
        HTTPException: On validation, rate limit, or processing errors
    """
    # Generate or use provided request ID
    request_id = x_request_id or str(uuid.uuid4())
    
    # Extract client identifier (IP or user agent)
    client_id = request.client.host if request.client else "unknown"
    
    # Check rate limiting
    if not _check_rate_limit(client_id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: maximum 60 requests per minute"
        )
    
    try:
        # Create user message
        user_message = UserMessage(
            thread_id=body.thread_id,
            text=body.text,
            context=body.context or {}
        )
        
        # Call dialogue-manager service via HTTP
        service_response = await _call_dialogue_manager_service(
            user_message=user_message,
            request_id=request_id
        )
        
        # Extract bot message from service response
        bot_message = service_response.get("bot_message", "")
        response_context = service_response.get("context")
        
        return WebhookResponse(
            request_id=request_id,
            bot_message=bot_message,
            context=response_context
        )
        
    except HTTPException:
        raise
    except DialogueManagerException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Dialogue processing error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )