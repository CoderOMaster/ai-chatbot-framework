from typing import Dict, Any, Optional
import logging
import os

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
import aiohttp

from .messenger import FacebookReceiver, validate_hub_signature, DialogueManagerClientProtocol
from app.dependencies import get_dialogue_manager

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)


async def get_facebook_config() -> Dict[str, Any]:
    """Retrieve Facebook integration settings.

    This dependency attempts to fetch the integration configuration from a
    dedicated integrations service if INTEGRATIONS_SERVICE_URL is configured.
    As a fallback (for monolith deployments) it will attempt to call the
    local integrations store dynamically. The returned dict is expected to
    contain keys such as 'verify', 'secret' and 'page_access_token'.
    """
    integrations_url = os.getenv("INTEGRATIONS_SERVICE_URL")

    # Prefer calling the integrations microservice when available
    if integrations_url:
        integrations_url = integrations_url.rstrip("/")
        url = f"{integrations_url}/integrations/facebook"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        integration = await resp.json()
                        if not integration or not integration.get("status"):
                            raise HTTPException(
                                status_code=404,
                                detail="Facebook integration not configured or disabled",
                            )
                        return integration.get("settings", {})
                    elif resp.status == 404:
                        raise HTTPException(status_code=404, detail="Facebook integration not found")
                    else:
                        text = await resp.text()
                        logger.error("Integrations service returned %s: %s", resp.status, text)
                        raise HTTPException(status_code=502, detail="Error fetching integration configuration")
        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to fetch Facebook integration from integrations service")
            raise HTTPException(status_code=502, detail="Could not contact integrations service")

    # Fallback for monolith: try to import the local store helper dynamically
    try:
        from app.admin.integrations import store as integrations_store  # type: ignore

        integration = await integrations_store.get_integration("facebook")
        if not integration or not integration.status:
            raise HTTPException(
                status_code=404, detail="Facebook integration not configured or disabled"
            )
        return integration.settings
    except HTTPException:
        raise
    except Exception:
        logger.exception("Could not load integration configuration from local store")
        raise HTTPException(status_code=500, detail="Integration configuration unavailable")


@router.get("/webhook")
async def verify_webhook(
    request: Request, config: Dict[str, Any] = Depends(get_facebook_config)
) -> Any:
    """Handle Facebook webhook verification (GET /webhook).

    Validates the hub.verify_token supplied by Facebook against the stored
    verify token in the integration settings.
    """
    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if hub_mode and token:
        if hub_mode == "subscribe" and token == config.get("verify"):
            try:
                return int(challenge)
            except Exception:
                return challenge
        raise HTTPException(status_code=403, detail="Invalid verification token")

    raise HTTPException(status_code=400, detail="Invalid request parameters")


@router.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    config: Dict[str, Any] = Depends(get_facebook_config),
    dialogue_manager: Optional[DialogueManagerClientProtocol] = Depends(get_dialogue_manager),
) -> Dict[str, Any]:
    """Handle incoming Facebook webhook events.

    This endpoint performs signature validation and delegates processing to a
    FacebookReceiver which is constructed with an injected dialogue-manager
    client (which may be a local manager or an HTTP client proxy).
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature", "")

    secret = config.get("secret", "")
    if not validate_hub_signature(body, signature, secret):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    if dialogue_manager is None:
        # Dialogue manager not available; cannot process messages
        logger.error("Dialogue manager client unavailable")
        raise HTTPException(status_code=503, detail="Dialogue manager unavailable")

    receiver = FacebookReceiver(config, dialogue_manager)

    try:
        data = await request.json()
        background_tasks.add_task(receiver.process_webhook_event, data)
        return {"success": True}
    except Exception as e:
        logger.error("Error processing webhook: %s", str(e))
        raise HTTPException(status_code=500, detail="Error processing webhook")