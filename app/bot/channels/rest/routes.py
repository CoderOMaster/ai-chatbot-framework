from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import os
import logging
import asyncio
import signal
from typing import Optional, Any, Dict

# Internal imports (kept as in original project layout)
from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager
from app.bot.dialogue_manager.dialogue_manager import (
    DialogueManager,
    DialogueManagerException,
)

# Optional DB pooling example
try:
    import asyncpg
except Exception:  # pragma: no cover - in case asyncpg is not available in some environments
    asyncpg = None

# Prometheus metrics (optional)
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
except Exception:  # pragma: no cover
    Counter = None
    Histogram = None
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

# Structured logging
try:
    from pythonjsonlogger import jsonlogger
except Exception:  # pragma: no cover
    jsonlogger = None


# Config from environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
DB_DSN = os.getenv("DB_DSN", "")  # e.g. postgresql://user:pass@host:5432/dbname
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("1", "true", "yes")
GRACEFUL_SHUTDOWN_TIMEOUT = int(os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT", "30"))

# Configure structured JSON logging
logger = logging.getLogger("dialogue_service")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
    handler = logging.StreamHandler()
    if jsonlogger is not None:
        fmt = jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            timestamp=True,
        )
        handler.setFormatter(fmt)
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
    logger.addHandler(handler)

app = FastAPI(title="dialogue-service", version="1.0.0")
router = APIRouter(prefix="/rest", tags=["rest"])

# Prometheus metrics (if available)
if METRICS_ENABLED and Counter is not None:
    REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
    REQUEST_LATENCY = Histogram("http_request_latency_seconds", "HTTP request latency", ["endpoint"])
else:
    REQUEST_COUNT = None
    REQUEST_LATENCY = None


# Pydantic model for inbound request body
class WebbookRequest(BaseModel):
    thread_id: str
    text: str
    context: Optional[Dict[str, Any]] = None


# Dependency for DB pool (if configured)
async def get_db_pool():
    pool = getattr(app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="database pool not initialized")
    return pool


# Graceful shutdown coordination
shutdown_event = asyncio.Event()


# Middleware-like helper for metrics and logging
@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    logger.info({"msg": "request_start", "method": method, "path": path})
    if REQUEST_LATENCY is not None:
        with REQUEST_LATENCY.labels(endpoint=path).time():
            response = await call_next(request)
    else:
        response = await call_next(request)
    status_code = response.status_code
    logger.info({"msg": "request_end", "method": method, "path": path, "status": status_code})
    if REQUEST_COUNT is not None:
        try:
            REQUEST_COUNT.labels(method=method, endpoint=path, http_status=str(status_code)).inc()
        except Exception:
            pass
    return response


@router.post("/webbook")
async def webbook(
    body: WebbookRequest,
    dialogue_manager: DialogueManager = Depends(get_dialogue_manager),
    db_pool=Depends(get_db_pool) if asyncpg is not None and DB_DSN else None,
):
    """
    Endpoint to converse with the chatbot.
    Delegates the request processing to DialogueManager.

    :return: JSON response with the chatbot's reply and context.
    """

    # Keep same logic as original but with validation and stronger error handling
    user_message = UserMessage(thread_id=body.thread_id, text=body.text, context=body.context)
    try:
        new_state = await dialogue_manager.process(user_message)
    except DialogueManagerException as e:
        logger.exception("DialogueManagerException occurred")
        # Use 'detail' for HTTPException; original code used 'message' which is not a parameter
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error in processing message")
        raise HTTPException(status_code=500, detail="internal server error")

    # Assume new_state.bot_message is serializable
    return JSONResponse(content=new_state.bot_message)


# Health & readiness endpoints
@router.get("/health")
async def health():
    return JSONResponse(content={"status": "ok"})


@router.get("/readiness")
async def readiness():
    # check if critical dependencies are up (DB pool and dialogue manager readiness)
    checks = {"db": True, "dialogue_manager": True}

    if asyncpg is not None and DB_DSN:
        pool = getattr(app.state, "db_pool", None)
        checks["db"] = pool is not None

    # If you have a way to check dialogue_manager readiness, add it; we assume OK if dependency can be fetched

    ready = all(checks.values())
    status_code = 200 if ready else 503
    return JSONResponse(status_code=status_code, content={"ready": ready, "checks": checks})


# Metrics endpoint (Prometheus)
if METRICS_ENABLED and generate_latest is not None:
    @app.get("/metrics")
    async def metrics():
        try:
            data = generate_latest()
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)
        except Exception as e:
            logger.exception("Failed to generate metrics")
            return PlainTextResponse("", status_code=500)


# Include router
app.include_router(router)


# Startup and shutdown handlers
@app.on_event("startup")
async def on_startup():
    logger.info({"msg": "starting application", "port": PORT})

    # Setup DB connection pool if DSN provided
    if asyncpg is not None and DB_DSN:
        try:
            app.state.db_pool = await asyncpg.create_pool(dsn=DB_DSN, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX)
            logger.info({"msg": "db_pool_created", "min": DB_POOL_MIN, "max": DB_POOL_MAX})
        except Exception:
            logger.exception("Failed to create DB pool")
            # Do not crash startup; readiness probe will fail until pool is available
            app.state.db_pool = None

    # Install SIGTERM handler for graceful shutdown
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(initiate_shutdown()))
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(initiate_shutdown()))
        logger.info({"msg": "signal_handlers_registered"})
    except NotImplementedError:
        # event loop signal handlers may not be implemented on some platforms (e.g., Windows)
        logger.warning({"msg": "signal_handlers_not_supported"})


async def initiate_shutdown():
    """Called when a SIGTERM or SIGINT arrives. Set an event and wait for tasks to complete."""
    logger.info({"msg": "shutdown_initiated"})
    shutdown_event.set()
    # Give the server some time to finish inflight requests
    await asyncio.sleep(0.1)


@app.on_event("shutdown")
async def on_shutdown():
    logger.info({"msg": "shutting down application"})

    # Close DB pool
    pool = getattr(app.state, "db_pool", None)
    if pool is not None:
        try:
            await pool.close()
            logger.info({"msg": "db_pool_closed"})
        except Exception:
            logger.exception("Error when closing db pool")

    # If DialogueManager needs explicit cleanup you can call it here. We assume get_dialogue_manager manages cleanup.


# If someone runs this module directly for local development
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "routes:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        lifespan="on",
    )
