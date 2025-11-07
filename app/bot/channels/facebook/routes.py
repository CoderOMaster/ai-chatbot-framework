from typing import Dict, Any, Optional, List
import logging
import json
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks

from app.admin.integrations.store import get_integration
from ai_chatbot_common.webhooks import (
    verify_facebook_signature,
    forward_http_json,
    send_to_sqs,
)
import os

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)


async def get_facebook_config():
    """Get Facebook integration configuration from store."""
    integration = await get_integration("facebook")
    if not integration or not integration.status:
        raise HTTPException(
            status_code=404, detail="Facebook integration not configured or disabled"
        )
    return integration.settings


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


@router.get("/webhook")
async def verify_webhook(
    request: Request, config: Dict[str, Any] = Depends(get_facebook_config)
):
    """Handle Facebook webhook verification."""
    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verify_token = _get_env("FACEBOOK_VERIFY_TOKEN", config.get("verify"))

    if hub_mode and token:
        if hub_mode == "subscribe" and token == verify_token:
            return int(challenge)
        raise HTTPException(status_code=403, detail="Invalid verification token")

    raise HTTPException(status_code=400, detail="Invalid request parameters")


def _forward_messages(entries: List[Dict[str, Any]]):
    forwarding_sqs = _get_env("FORWARDING_SQS_URL")
    forwarding_endpoint = _get_env("FORWARDING_ENDPOINT")

    for entry in entries or []:
        page_id = entry.get("id")
        for messaging_event in entry.get("messaging", []):
            sender_id = (messaging_event.get("sender") or {}).get("id")
            if not sender_id:
                continue
            timestamp = messaging_event.get("timestamp")
            is_postback = bool(messaging_event.get("postback"))
            text: Optional[str] = None
            if messaging_event.get("message") and "text" in messaging_event["message"]:
                text = messaging_event["message"]["text"]
            elif is_postback:
                text = (messaging_event.get("postback") or {}).get("payload")

            if text is None:
                continue

            user_message = {
                "thread_id": sender_id,
                "text": text,
                "context": {
                    "channel": "facebook",
                    "page_id": page_id,
                    "timestamp": timestamp,
                    "is_postback": is_postback,
                },
            }

            if forwarding_sqs:
                send_to_sqs(forwarding_sqs, user_message)
            else:
                headers = {"x-source": "facebook-webhook"}
                forward_http_json(forwarding_endpoint or "", user_message, headers=headers)


@router.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    config: Dict[str, Any] = Depends(get_facebook_config),
):
    """Handle incoming Facebook webhook events by validating and forwarding."""
    body = await request.body()

    # Support both headers. Starlette provides case-insensitive lookup.
    signature = request.headers.get("X-Hub-Signature") or request.headers.get(
        "X-Hub-Signature-256", ""
    )

    app_secret = _get_env("FACEBOOK_APP_SECRET", config.get("secret", "")) or ""

    if not app_secret or not verify_facebook_signature(app_secret, body, signature):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        entries = data.get("entry", [])
        # Offload forwarding to background task to avoid blocking event loop with sync I/O
        background_tasks.add_task(_forward_messages, entries)
        return {"success": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing webhook")