from typing import Dict, Any, Optional
import asyncio
import logging
import logging.handlers
import json
import os
import signal
from fastapi import FastAPI, APIRouter, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# Internal imports (kept as in original codebase)
from app.admin.integrations.store import get_integration
from app.dependencies import get_dialogue_manager
from app.bot.dialogue_manager.dialogue_manager import DialogueManager

# Try absolute import first, fall back to relative if necessary
try:
    from app.bot.channels.facebook.messenger import FacebookReceiver
except Exception:
    try:
        from .messenger import FacebookReceiver  # type: ignore
    except Exception:
        FacebookReceiver = None  # type: ignore

# Optional imports
try:
    import asyncpg
except Exception:
    asyncpg = None  # type: ignore

try:
    from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
    from prometheus_client import REGISTRY
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False

# Environment variables
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_URL = os.getenv("DATABASE_URL", "")
PROMETHEUS_ENABLED = os.getenv("PROMETHEUS_ENABLED", "false").lower() in ("1", "true", "yes")
READINESS_PATH = os.getenv("READINESS_PATH", "/ready")

# Structured JSON logger
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger("facebook_microservice")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

# FastAPI app and router
app = FastAPI(title="facebook-webhook-service")
router = APIRouter(prefix="/facebook", tags=["facebook"])

# Connection pool manager (optional, uses asyncpg when available)
class DBPool:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None

    async def init(self):
        if not self.dsn:
            logger.info("No DATABASE_URL provided; skipping DB pool initialization")
            return
        if not asyncpg:
            logger.warning("asyncpg not installed; skipping DB pool initialization")
            return
        try:
            logger.info("Initializing DB connection pool")
            self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=10)
            logger.info("DB pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize DB pool: {e}")
            self.pool = None

    async def close(self):
        if self.pool:
            try:
                await self.pool.close()
                logger.info("DB pool closed")
            except Exception as e:
                logger.error(f"Error closing DB pool: {e}")

# Attach DB pool to app.state
app.state.db_pool = DBPool(DATABASE_URL)

# Readiness flag
app.state.ready = False

# Prometheus metrics (optional)
if PROMETHEUS_AVAILABLE and PROMETHEUS_ENABLED:
    REQUEST_COUNT = Counter("facebook_requests_total", "Total HTTP requests received", ["method", "endpoint", "http_status"])
else:
    REQUEST_COUNT = None


async def get_facebook_config() -> Any:
    """Get Facebook integration configuration from store."""
    integration = await get_integration("facebook")
    if not integration or not integration.status:
        raise HTTPException(
            status_code=404, detail="Facebook integration not configured or disabled"
        )
    return integration.settings


@router.get("/webhook")
async def verify_webhook(request: Request, config: Dict[str, Any] = Depends(get_facebook_config)):
    """Handle Facebook webhook verification."""
    hub_mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if hub_mode and token:
        if hub_mode == "subscribe" and token == config.get("verify"):
            # Facebook expects a plain text response with the challenge
            return PlainTextResponse(str(challenge))
        raise HTTPException(status_code=403, detail="Invalid verification token")

    raise HTTPException(status_code=400, detail="Invalid request parameters")


@router.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    config: Dict[str, Any] = Depends(get_facebook_config),
    dialogue_manager: DialogueManager = Depends(get_dialogue_manager),
):
    """Handle incoming Facebook webhook events."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature", "")

    if not FacebookReceiver:
        logger.error("FacebookReceiver implementation not available")
        raise HTTPException(status_code=500, detail="Receiver not configured")

    facebook = FacebookReceiver(config, dialogue_manager)

    if not facebook.validate_hub_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        data = await request.json()
        # Delegate processing to background task so we return quickly
        background_tasks.add_task(facebook.process_webhook_event, data)

        if REQUEST_COUNT is not None:
            REQUEST_COUNT.labels(method="POST", endpoint="/facebook/webhook", http_status="200").inc()

        return {"success": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        if REQUEST_COUNT is not None:
            REQUEST_COUNT.labels(method="POST", endpoint="/facebook/webhook", http_status="500").inc()
        raise HTTPException(status_code=500, detail="Error processing webhook")


# Health and readiness endpoints
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get(READINESS_PATH)
async def readiness():
    if app.state.ready:
        return {"status": "ready"}
    raise HTTPException(status_code=503, detail="service not ready")


# Optional metrics endpoint
if PROMETHEUS_AVAILABLE and PROMETHEUS_ENABLED:
    @app.get("/metrics")
    async def metrics():
        data = generate_latest(REGISTRY)
        return PlainTextResponse(content=data, media_type=CONTENT_TYPE_LATEST)

# Include router
app.include_router(router)


# Startup and shutdown events
@app.on_event("startup")
async def on_startup():
    logger.info("Starting facebook webhook service")
    # Init DB pool
    try:
        await app.state.db_pool.init()
    except Exception as e:
        logger.error(f"DB pool startup error: {e}")

    # Mark ready after initialization
    app.state.ready = True
    logger.info("Service marked as ready")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down facebook webhook service")
    app.state.ready = False
    try:
        await app.state.db_pool.close()
    except Exception as e:
        logger.error(f"DB pool shutdown error: {e}")


# Graceful shutdown helper for non-uvicorn contexts (uvicorn handles signals itself)
def _setup_signal_handlers(loop: Optional[asyncio.AbstractEventLoop] = None):
    loop = loop or asyncio.get_event_loop()

    async def _handle_exit(sig):
        logger.info(f"Received exit signal {sig.name}; initiating shutdown")
        app.state.ready = False
        # Allow other coroutines to run and finish
        await asyncio.sleep(0.1)
        # Trigger FastAPI shutdown event by stopping the loop
        loop.stop()

    try:
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(_handle_exit(s)))
    except NotImplementedError:
        # Signals not implemented on some platforms (Windows)
        logger.debug("Signal handlers not supported on this platform")


# If launched as a script, set up signal handlers
if __name__ == "__main__":
    import uvicorn

    _setup_signal_handlers()
    uvicorn.run("app.bot.channels.facebook.routes:app", host=HOST, port=PORT, log_level=LOG_LEVEL.lower(), lifespan="on")
