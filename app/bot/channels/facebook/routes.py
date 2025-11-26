from typing import Dict, Any, Optional
import logging
import hashlib
import hmac
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from .messenger import FacebookReceiver

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)

# Webhook verification cache: {token_hash: (timestamp, is_valid)}
_verification_cache: Dict[str, tuple[datetime, bool]] = {}
VERIFICATION_CACHE_TTL = 3600  # 1 hour


async def get_facebook_config_from_store() -> Dict[str, Any]:
    """
    Get Facebook integration configuration from store.
    
    In Lambda environment, this would typically query DynamoDB or call
    a configuration service. For now, uses environment variables.
    
    Returns:
        Configuration dict with 'page_access_token', 'secret', and 'verify' keys
        
    Raises:
        HTTPException: If configuration is not available or disabled
    """
    # TODO: Replace with actual service call or DB query
    # For Lambda deployment, consider using boto3 to fetch from Secrets Manager
    # or a dedicated config service endpoint
    import os
    
    verify_token = os.getenv("FACEBOOK_VERIFY_TOKEN")
    page_access_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
    secret = os.getenv("FACEBOOK_SECRET")
    dialogue_manager_url = os.getenv("DIALOGUE_MANAGER_URL")
    
    if not all([verify_token, page_access_token, secret, dialogue_manager_url]):
        raise HTTPException(
            status_code=500, 
            detail="Facebook integration not configured"
        )
    
    return {
        "verify": verify_token,
        "page_access_token": page_access_token,
        "secret": secret,
        "dialogue_manager_url": dialogue_manager_url,
    }


def _get_verification_cache_key(token: str, challenge: str) -> str:
    """Generate cache key for webhook verification."""
    return hashlib.sha256(f"{token}:{challenge}".encode()).hexdigest()


def _is_verification_cached(cache_key: str) -> bool:
    """Check if verification result is cached and still valid."""
    if cache_key not in _verification_cache:
        return False
    
    timestamp, is_valid = _verification_cache[cache_key]
    if datetime.utcnow() - timestamp > timedelta(seconds=VERIFICATION_CACHE_TTL):
        del _verification_cache[cache_key]
        return False
    
    return is_valid


def _cache_verification(cache_key: str, is_valid: bool) -> None:
    """Cache webhook verification result."""
    _verification_cache[cache_key] = (datetime.utcnow(), is_valid)


@router.get("/webhook")
async def verify_webhook(request: Request) -> int:
    """
    Handle Facebook webhook verification.
    
    Validates the webhook subscription request from Facebook.
    Implements caching to reduce repeated verification overhead.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Challenge value as integer
        
    Raises:
        HTTPException: If verification fails
    """
    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if not hub_mode or not token or not challenge:
        raise HTTPException(status_code=400, detail="Invalid request parameters")

    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="Invalid hub mode")

    # Check cache first
    cache_key = _get_verification_cache_key(token, challenge)
    if _is_verification_cached(cache_key):
        logger.debug("Webhook verification from cache")
        return int(challenge)

    # Get config and verify token
    try:
        config = await get_facebook_config_from_store()
    except HTTPException:
        raise HTTPException(status_code=403, detail="Invalid verification token")

    if token == config["verify"]:
        _cache_verification(cache_key, True)
        return int(challenge)
    
    _cache_verification(cache_key, False)
    raise HTTPException(status_code=403, detail="Invalid verification token")


@router.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    request: Request,
) -> Dict[str, bool]:
    """
    Handle incoming Facebook webhook events.
    
    Validates request signature, deduplicates messages, and processes
    events asynchronously via background tasks.
    
    Args:
        background_tasks: FastAPI background tasks
        request: FastAPI request object
        
    Returns:
        Success response dict
        
    Raises:
        HTTPException: If signature validation fails or processing error occurs
    """
    try:
        config = await get_facebook_config_from_store()
    except HTTPException as e:
        logger.error(f"Failed to get Facebook config: {e}")
        raise HTTPException(status_code=500, detail="Configuration error")

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature", "")

    # Validate signature
    if not _validate_hub_signature(body, signature, config["secret"]):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        data = await request.json()
        
        # Initialize receiver with HTTP URL for dialogue manager
        facebook = FacebookReceiver(
            config=config,
            dialogue_manager_url=config["dialogue_manager_url"],
        )
        
        # Process webhook event asynchronously
        background_tasks.add_task(facebook.process_webhook_event, data)

        return {"success": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error processing webhook")


def _validate_hub_signature(
    request_payload: bytes, 
    hub_signature_header: str, 
    secret: str
) -> bool:
    """
    Validate the request signature from Facebook.
    
    Args:
        request_payload: Raw request body bytes
        hub_signature_header: X-Hub-Signature header value (format: "sha1=...")
        secret: Facebook app secret
        
    Returns:
        True if signature is valid, False otherwise
    """
    try:
        hash_method, hub_signature = hub_signature_header.split("=")
        digest_module = getattr(hashlib, hash_method)
        hmac_object = hmac.new(
            bytearray(secret, "utf8"), 
            request_payload, 
            digest_module
        )
        generated_hash = hmac_object.hexdigest()
        return hub_signature == generated_hash
    except Exception as e:
        logger.warning(f"Signature validation failed: {e}")
        return False