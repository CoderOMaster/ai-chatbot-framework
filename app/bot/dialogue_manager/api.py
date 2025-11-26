"""
HTTP API for Dialogue Manager microservice.

This module provides a FastAPI application that exposes the DialogueManager
as a REST API, enabling external services (web channels, REST clients, etc.)
to call dialogue processing without importing the class directly.

The API can be deployed as a standalone microservice or embedded in the
monolithic FastAPI backend. It uses dependency injection to manage the
DialogueManager lifecycle and database connections.

Typical deployment:
    uvicorn app.bot.dialogue_manager.api:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field

from app.bot.dialogue_manager.dialogue_manager import (
    DialogueManager,
    DialogueManagerException,
)
from app.bot.dialogue_manager.models import UserMessage
from app.bot.memory.models import State
from app.database import init_db, close_db, get_db
from app.common.config import get_settings

logger = logging.getLogger("dialogue_manager_api")


class ProcessMessageRequest(BaseModel):
    """Request DTO for dialogue processing.
    
    Attributes:
        thread_id: Unique identifier for the conversation thread
        text: User message text
        channel: Optional channel identifier (e.g., "rest", "facebook", "web")
        user_id: Optional user identifier
        metadata: Optional additional metadata as dict
    """
    thread_id: str = Field(..., description="Unique conversation thread ID")
    text: str = Field(..., description="User message text")
    channel: Optional[str] = Field(None, description="Channel identifier")
    user_id: Optional[str] = Field(None, description="User identifier")
    metadata: Optional[dict] = Field(None, description="Additional metadata")


class ProcessMessageResponse(BaseModel):
    """Response DTO for dialogue processing.
    
    Attributes:
        thread_id: Conversation thread ID
        bot_message: List of bot response messages
        state: Current conversation state
        intent_id: Detected intent ID
        parameters: Extracted parameters
        complete: Whether the intent is complete
    """
    thread_id: str = Field(..., description="Conversation thread ID")
    bot_message: list = Field(..., description="Bot response messages")
    state: dict = Field(..., description="Current conversation state")
    intent_id: Optional[str] = Field(None, description="Detected intent ID")
    parameters: dict = Field(default_factory=dict, description="Extracted parameters")
    complete: bool = Field(..., description="Whether intent is complete")


class HealthResponse(BaseModel):
    """Health check response.
    
    Attributes:
        status: Service status ("healthy" or "unhealthy")
        nlu_ready: Whether NLU pipeline is initialized
    """
    status: str = Field(..., description="Service status")
    nlu_ready: bool = Field(..., description="NLU pipeline status")


# Global dialogue manager instance
_dialogue_manager: Optional[DialogueManager] = None


async def get_dialogue_manager() -> DialogueManager:
    """
    Dependency injection provider for DialogueManager.
    
    Returns the global DialogueManager instance, ensuring it's initialized.
    
    Returns:
        DialogueManager: The initialized dialogue manager instance
        
    Raises:
        RuntimeError: If dialogue manager is not initialized
    """
    if _dialogue_manager is None:
        raise RuntimeError("Dialogue manager not initialized")
    return _dialogue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for startup and shutdown.
    
    Initializes database connection and DialogueManager on startup,
    and closes connections on shutdown.
    
    Args:
        app: FastAPI application instance
    """
    global _dialogue_manager
    
    # Startup
    logger.info("Starting Dialogue Manager API")
    settings = get_settings()
    
    try:
        await init_db(settings)
        logger.info("Database initialized")
        
        db = get_db()
        _dialogue_manager = await DialogueManager.from_config(db=db)
        logger.info("Dialogue Manager initialized")
        
    except Exception as e:
        logger.error(f"Failed to initialize Dialogue Manager: {e}", exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Dialogue Manager API")
    try:
        await close_db()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}", exc_info=True)


# Create FastAPI application
app = FastAPI(
    title="Dialogue Manager API",
    description="REST API for dialogue processing and conversation management",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check(
    dialogue_manager: DialogueManager = Depends(get_dialogue_manager),
) -> HealthResponse:
    """
    Health check endpoint.
    
    Returns the service status and NLU pipeline readiness.
    
    Args:
        dialogue_manager: Injected DialogueManager instance
        
    Returns:
        HealthResponse: Service health status
    """
    nlu_ready = dialogue_manager.nlu_pipeline is not None
    status = "healthy" if nlu_ready else "degraded"
    
    return HealthResponse(
        status=status,
        nlu_ready=nlu_ready,
    )


@app.post("/process", response_model=ProcessMessageResponse)
async def process_message(
    request: ProcessMessageRequest,
    dialogue_manager: DialogueManager = Depends(get_dialogue_manager),
) -> ProcessMessageResponse:
    """
    Process a user message and return dialogue state.
    
    This is the main endpoint for dialogue processing. It accepts a user message,
    processes it through the NLU pipeline and intent handling logic, and returns
    the updated conversation state and bot response.
    
    Args:
        request: ProcessMessageRequest containing thread_id, text, and optional metadata
        dialogue_manager: Injected DialogueManager instance
        
    Returns:
        ProcessMessageResponse: Updated state and bot response
        
    Raises:
        HTTPException: If processing fails or NLU pipeline is not ready
    """
    try:
        # Create UserMessage from request
        user_message = UserMessage(
            thread_id=request.thread_id,
            text=request.text,
            channel=request.channel,
            user_id=request.user_id,
            metadata=request.metadata or {},
        )
        
        # Process message
        state: State = await dialogue_manager.process(user_message)
        
        # Build response
        return ProcessMessageResponse(
            thread_id=state.thread_id,
            bot_message=state.bot_message or [],
            state=state.to_dict(),
            intent_id=state.intent.get("id") if state.intent else None,
            parameters=state.extracted_parameters or {},
            complete=state.complete,
        )
        
    except DialogueManagerException as e:
        logger.error(f"Dialogue processing error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during message processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/reload-models")
async def reload_models(
    models_dir: str = "/models",
    dialogue_manager: DialogueManager = Depends(get_dialogue_manager),
) -> dict:
    """
    Reload NLU models from disk.
    
    This endpoint is called by the training worker after models are successfully
    trained. It signals the dialogue manager to reload the NLU pipeline from the
    specified directory.
    
    Args:
        models_dir: Directory containing trained models
        dialogue_manager: Injected DialogueManager instance
        
    Returns:
        dict: Status message
    """
    try:
        dialogue_manager.update_model(models_dir)
        logger.info(f"Models reloaded from {models_dir}")
        return {"status": "success", "message": "Models reloaded"}
    except Exception as e:
        logger.error(f"Failed to reload models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reload models: {e}")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )