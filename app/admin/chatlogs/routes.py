import os
import sys
import signal
import asyncio
import logging
import time
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

# Import the (existing) store module that interacts with DB
import app.admin.chatlogs.store as store

# Optional Prometheus integration
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    PROM_AVAILABLE = True
except Exception:
    PROM_AVAILABLE = False

# JSON logging
try:
    from pythonjsonlogger import jsonlogger
    JSONLOG_AVAILABLE = True
except Exception:
    JSONLOG_AVAILABLE = False

# ------------------------------------------------------------------
# Configuration from environment
# ------------------------------------------------------------------
SERVICE_NAME = os.getenv("SERVICE_NAME", "chatlogs-service")
SERVICE_ENV = os.getenv("SERVICE_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_DSN = os.getenv("DB_DSN", None)  # e.g. postgres://user:pass@host:5432/db
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
METRICS_PATH = os.getenv("METRICS_PATH", "/metrics")
GRACEFUL_TIMEOUT = int(os.getenv("GRACEFUL_TIMEOUT", "25"))

# ------------------------------------------------------------------
# Logger setup (structured JSON logging if available)
# ------------------------------------------------------------------
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)
handler = logging.StreamHandler(sys.stdout)
if JSONLOG_AVAILABLE:
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)d"
    )
    handler.setFormatter(fmt)
else:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s (%(module)s:%(lineno)d)"
    )
    handler.setFormatter(fmt)
root_logger.handlers = []
root_logger.addHandler(handler)
logger = logging.getLogger(SERVICE_NAME)

# ------------------------------------------------------------------
# Prometheus metrics (optional)
# ------------------------------------------------------------------
if PROM_AVAILABLE:
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "http_status"],
    )

    REQUEST_LATENCY = Histogram(
        "http_request_latency_seconds",
        "HTTP request latency in seconds",
        ["method", "endpoint"],
    )
else:
    REQUEST_COUNT = None
    REQUEST_LATENCY = None

# ------------------------------------------------------------------
# FastAPI app and router
# ------------------------------------------------------------------
app = FastAPI(title="Chatlogs Service", version="1.0.0")
router = APIRouter(prefix="/chatlogs", tags=["chatlogs"])

# Graceful shutdown helper
shutdown_event = asyncio.Event()


async def _maybe_call_async(func, *args, **kwargs):
    """Call func with await if coroutine, otherwise call it synchronously.
    This helps integrate with store implementations that may be sync or async.
    """
    if asyncio.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    else:
        return func(*args, **kwargs)


# ------------------------------------------------------------------
# Routes (original logic preserved)
# ------------------------------------------------------------------

@router.get("/")
async def list_chatlogs(
    page: int = 1,
    limit: int = 10,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    """Get paginated chat conversation history with optional date filtering"""
    try:
        # call into store.list_chatlogs (preserve original behavior)
        result = await _maybe_call_async(store.list_chatlogs, page, limit, start_date, end_date)
        return result
    except Exception as exc:  # keep concise error handling
        logger.exception("Failed to list chatlogs")
        return JSONResponse({"error": "failed to list chatlogs"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{thread_id}")
async def get_chat_thread(thread_id: str):
    """Get complete conversation history for a specific thread"""
    try:
        conversation = await _maybe_call_async(store.get_chat_thread, thread_id)
        if not conversation:
            return JSONResponse({"error": "Conversation not found"}, status_code=status.HTTP_404_NOT_FOUND)
        return conversation
    except Exception:
        logger.exception("Failed to get chat thread %s", thread_id)
        return JSONResponse({"error": "failed to get conversation"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


app.include_router(router)

# ------------------------------------------------------------------
# Health, readiness and metrics endpoints
# ------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness probe. Should be cheap and always true if service process is alive."""
    return JSONResponse({"status": "ok"})


@app.get("/readiness")
async def readiness():
    """Readiness probe. Check DB connectivity if DB_DSN is configured."""
    if DB_DSN is None:
        # If no DB configured, assume the service is ready
        return JSONResponse({"status": "ready", "db": "not_configured"})

    # Try a lightweight DB ping using the store if available
    try:
        # Prefer store.ping or store.ping_pool
        if hasattr(store, "ping"):
            await _maybe_call_async(getattr(store, "ping"))
        elif hasattr(store, "ping_pool"):
            await _maybe_call_async(getattr(store, "ping_pool"))
        else:
            # attempt a small query via a known helper in store to validate pool
            if hasattr(store, "get_conn"):
                conn = await _maybe_call_async(getattr(store, "get_conn"))
                # If a connection object has execute method, try a simple nop
                if hasattr(conn, "execute"):
                    try:
                        result = await _maybe_call_async(getattr(conn, "execute"), "SELECT 1")
                    finally:
                        # try to release if pool offers release
                        if hasattr(store, "release_conn"):
                            await _maybe_call_async(getattr(store, "release_conn"), conn)
        return JSONResponse({"status": "ready", "db": "ok"})
    except Exception:
        logger.exception("Readiness check: DB ping failed")
        return JSONResponse({"status": "not_ready", "db": "unreachable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


if PROM_AVAILABLE:
    @app.get(METRICS_PATH)
    async def metrics():
        # Expose Prometheus metrics
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# ------------------------------------------------------------------
# Middleware for logging and metrics
# ------------------------------------------------------------------

@app.middleware("http")
async def add_logging_and_metrics(request: Request, call_next):
    start_time = time.time()
    path = request.url.path
    method = request.method

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        logger.exception("Unhandled error in request")
        # Re-raise so FastAPI/ASGI can handle yet we logged it
        raise
    finally:
        duration = time.time() - start_time
        # Structured log entry
        logger.info(
            "request_completed",
            extra={
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": int(duration * 1000),
            },
        )
        if PROM_AVAILABLE and REQUEST_COUNT and REQUEST_LATENCY:
            try:
                REQUEST_COUNT.labels(method=method, endpoint=path, http_status=str(status_code)).inc()
                REQUEST_LATENCY.labels(method=method, endpoint=path).observe(duration)
            except Exception:
                # metrics should not break the request path
                logger.debug("Failed to update metrics")

    return response

# ------------------------------------------------------------------
# Startup/shutdown lifecycle: connection pooling and signal handling
# ------------------------------------------------------------------

async def _init_db_pool():
    """Attempt to initialize DB connection pool using the store module.
    We try a few common function names to remain compatible with different store implementations.
    """
    if DB_DSN is None:
        logger.info("DB_DSN not set; skipping DB pool initialization")
        return

    logger.info("Initializing DB pool from DSN")
    # Look for known init functions
    tried = []
    try:
        if hasattr(store, "init_pool"):
            tried.append("init_pool")
            await _maybe_call_async(getattr(store, "init_pool"), DB_DSN, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX)
            return

        if hasattr(store, "init"):
            tried.append("init")
            await _maybe_call_async(getattr(store, "init"), DB_DSN)
            return

        if hasattr(store, "connect_pool"):
            tried.append("connect_pool")
            await _maybe_call_async(getattr(store, "connect_pool"), DB_DSN, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX)
            return

        # Fallback: if the store expects environment variables itself, call store.setup() if exists
        if hasattr(store, "setup"):
            tried.append("setup")
            await _maybe_call_async(getattr(store, "setup"))
            return

        logger.warning("No known pool init function in store. Tried: %s. Proceeding without explicit pool init.", tried)
    except Exception:
        logger.exception("Failed initializing DB pool using %s", tried)
        raise


async def _close_db_pool():
    """Attempt to gracefully close DB pool using the store module.
    """
    try:
        if hasattr(store, "close_pool"):
            await _maybe_call_async(getattr(store, "close_pool"))
            return
        if hasattr(store, "close"):
            await _maybe_call_async(getattr(store, "close"))
            return
        logger.info("No explicit close function found in store - skipping")
    except Exception:
        logger.exception("Error while closing DB pool")


@app.on_event("startup")
async def on_startup():
    logger.info("Starting %s (env=%s)", SERVICE_NAME, SERVICE_ENV)
    try:
        await _init_db_pool()
    except Exception:
        logger.exception("DB initialization failed during startup")
        # If DB is critical, you might want to raise here to prevent app from starting
        # For now, we continue so liveness shows up but readiness will fail.

    # register signal handlers for graceful shutdown (works when running in main thread)
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(_handle_termination()))
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(_handle_termination()))
    except NotImplementedError:
        # Signals aren't available on Windows/uvloop in some environments
        logger.debug("Signal handlers not installed (platform limitation)")


async def _handle_termination():
    logger.info("Received termination signal; initiating graceful shutdown. Waiting up to %s seconds", GRACEFUL_TIMEOUT)
    try:
        await _close_db_pool()
    except Exception:
        logger.exception("Error during pool close on termination")
    # set shutdown event so background tasks can react
    shutdown_event.set()
    # Wait briefly to allow pending requests to finish
    await asyncio.sleep(0.01)


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down %s", SERVICE_NAME)
    try:
        await _close_db_pool()
    except Exception:
        logger.exception("Error closing DB pool during shutdown")


# If run directly with `python -m <module>` we provide a small start helper
if __name__ == "__main__":
    # This module is not intended to be started directly in production; prefer uvicorn/gunicorn.
    import uvicorn

    workers = int(os.getenv("WORKERS", "1"))
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level=LOG_LEVEL.lower(), workers=workers)
