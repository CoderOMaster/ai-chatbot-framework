from typing import Dict, Any, Optional, Protocol
import asyncio
import json
import logging
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse

from app.admin.integrations.store import get_integration
from app.dependencies import get_dialogue_manager
from app.bot.channels.facebook.messenger import FacebookReceiver, validate_hub_signature

router = APIRouter(prefix="/facebook", tags=["facebook"])
logger = logging.getLogger(__name__)

# Simple in-memory cache to avoid repeated DB hits for integration config.
_integration_cache: Optional[Dict[str, Any]] = None


class DialogueManagerProtocol(Protocol):
    """Minimal protocol used by the Facebook receiver so tests can provide fakes."""

    async def process(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - behavior verified elsewhere
        ...


async def get_facebook_config() -> Dict[str, Any]:
    """Get Facebook integration configuration from store with a simple in-memory cache.

    Caches the integration document for the lifetime of the process to reduce
    database hits at the webhook edge. This keeps the implementation backward
    compatible while allowing replacement with a smarter cache if needed.
    """
    global _integration_cache
    if _integration_cache is not None:
        return _integration_cache

    integration = await get_integration("facebook")
    if not integration or not integration.status:
        raise HTTPException(
            status_code=404, detail="Facebook integration not configured or disabled"
        )

    # Store the raw settings dict so callers get the previous shape.
    _integration_cache = integration.settings
    return _integration_cache


async def _validate_facebook_signature(request: Request, config: Dict[str, Any] = Depends(get_facebook_config)) -> None:
    """FastAPI dependency that validates the X-Hub-Signature header and stores
    the parsed JSON body on the request.state so route handlers don't need to
    re-read the body stream.

    Raises HTTPException(403) on invalid signature.
    """
    raw_body = await request.body()
    # Preserve raw body for downstream handlers / logging
    request.state.raw_body = raw_body

    signature = request.headers.get("X-Hub-Signature", "")
    secret = config.get("secret", "")

    if not validate_hub_signature(raw_body, signature, secret):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    # Parse JSON once and cache it on the request state. If parse fails we let
    # the route handler return a 400.
    try:
        request.state.parsed_json = json.loads(raw_body.decode("utf8")) if raw_body else {}
    except Exception:
        request.state.parsed_json = None


async def _require_ready_dialogue_manager(dmgr = Depends(get_dialogue_manager)) -> DialogueManagerProtocol:
    """Ensure the dialogue manager is available and fail fast with 503 if not.

    This prevents webhook handlers from accepting events when the runtime
    responsible for processing them is not ready.
    """
    if dmgr is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Dialogue manager not ready")
    return dmgr  # type: ignore[return-value]


def get_facebook_receiver(config: Dict[str, Any] = Depends(get_facebook_config),
                          dialogue_manager: DialogueManagerProtocol = Depends(_require_ready_dialogue_manager)) -> FacebookReceiver:
    """Construct a FacebookReceiver instance. Provided as a dependency so tests
    and higher-level wiring can replace it with a mock or alternate implementation.
    """
    return FacebookReceiver(config, dialogue_manager)


def _enqueue_webhook_event(data: Dict[str, Any], receiver: FacebookReceiver) -> None:
    """Enqueue the webhook processing to the event loop immediately and return.

    This keeps the HTTP response fast (202 Accepted) and allows the runtime to
    process the payload asynchronously. Replace this with an orchestration
    queue client if available (e.g. Kafka, Redis Streams) for durable delivery.
    """
    async def _runner() -> None:
        try:
            await receiver.process_webhook_event(data)
        except Exception as exc:  # ensure background failures are logged
            logger.exception("background webhook processing failed: %s", exc)

    # Schedule background work without blocking the response. Use create_task so
    # the task runs on the default loop; frameworks with external orchestrators
    # should provide their own enqueue implementation.
    try:
        asyncio.create_task(_runner())
    except RuntimeError:
        # If there's no running loop (unlikely under FastAPI) run in a new task
        loop = asyncio.get_event_loop()
        loop.create_task(_runner())


@router.get("/webhook")
async def verify_webhook(request: Request, config: Dict[str, Any] = Depends(get_facebook_config)) -> Any:
    """Handle Facebook webhook verification (GET).

    Uses the cached integration configuration to validate the verify token.
    """
    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if hub_mode and token:
        if hub_mode == "subscribe" and token == config["verify"]:
            try:
                return int(challenge)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid challenge value")
        raise HTTPException(status_code=403, detail="Invalid verification token")

    raise HTTPException(status_code=400, detail="Invalid request parameters")


@router.post("/webhook")
async def webhook(
    request: Request,
    _validated: None = Depends(_validate_facebook_signature),
    receiver: FacebookReceiver = Depends(get_facebook_receiver),
):
    """Accept incoming Facebook webhook events, validate signature via a
    dependency and enqueue processing to keep the webhook responsive.

    Returns 202 Accepted immediately while processing continues asynchronously.
    """
    data = getattr(request.state, "parsed_json", None)
    if data is None:
        # Attempt to parse if the dependency failed to parse the payload.
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Enqueue background processing via an orchestration-friendly abstraction.
    _enqueue_webhook_event(data, receiver)

    return JSONResponse({"accepted": True}, status_code=status.HTTP_202_ACCEPTED)