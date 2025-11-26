"""
Facebook Messenger webhook routes for Lambda deployment.

This module implements webhook verification and message routing for Facebook Messenger.
It validates webhook signatures locally and delegates message processing to the
dialogue-manager service via FacebookReceiver's HTTP client interface.

Designed to be deployed as a Lambda function behind API Gateway, with all state
managed by the dialogue-manager microservice.
"""

from typing import Dict, Any
import logging
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from app.admin.integrations.store import get_integration
from app.dependencies import get_dialogue_manager
from .messenger import FacebookReceiver

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)


async def get_facebook_config() -> Dict[str, Any]:
    """Get Facebook integration configuration from store.
    
    Returns:
        Dict[str, Any]: Configuration dictionary with page_access_token, secret, verify token
        
    Raises:
        HTTPException: If integration not configured or disabled
    """
    integration = await get_integration("facebook")
    if not integration or not integration.status:
        raise HTTPException(
            status_code=404, detail="Facebook integration not configured or disabled"
        )
    return integration.settings


@router.get("/webhook")
async def verify_webhook(
    request: Request, config: Dict[str, Any] = Depends(get_facebook_config)
) -> int:
    """Handle Facebook webhook verification.
    
    Validates the webhook verification request from Facebook during setup.
    
    Args:
        request: FastAPI request object
        config: Facebook integration configuration
        
    Returns:
        int: Challenge value if verification succeeds
        
    Raises:
        HTTPException: If verification fails
    """
    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if hub_mode and token:
        if hub_mode == "subscribe" and token == config["verify"]:
            return int(challenge)
        raise HTTPException(status_code=403, detail="Invalid verification token")

    raise HTTPException(status_code=400, detail="Invalid request parameters")


@router.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    config: Dict[str, Any] = Depends(get_facebook_config),
    dialogue_manager_client: Any = Depends(get_dialogue_manager),
) -> Dict[str, bool]:
    """Handle incoming Facebook webhook events.
    
    Validates webhook signature, extracts messaging events, and queues them
    for background processing via FacebookReceiver.
    
    Args:
        background_tasks: FastAPI background tasks queue
        request: FastAPI request object with webhook payload
        config: Facebook integration configuration
        dialogue_manager_client: Dialogue manager client (local or HTTP)
        
    Returns:
        Dict[str, bool]: Success response
        
    Raises:
        HTTPException: If signature validation or processing fails
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature", "")

    # Initialize FacebookReceiver with HTTP client for dialogue manager
    facebook = FacebookReceiver(config, dialogue_manager_client)

    if not facebook.validate_hub_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        data = await request.json()
        background_tasks.add_task(facebook.process_webhook_event, data)

        return {"success": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing webhook")