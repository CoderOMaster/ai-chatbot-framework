import os
import sys
import asyncio
import signal
import logging
from typing import Callable, Optional

from fastapi import FastAPI, APIRouter, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger

# Optional Prometheus integration
try:
    from prometheus_client import Counter, Histogram
    from prometheus_client import make_asgi_app
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False

# Import existing application modules (unchanged logic)
from app.admin.intents import store
from app.admin.intents.schemas import Intent

# Environment-driven configuration
HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_URL = os.getenv("DB_URL", "postgresql://user:pass@localhost:5432/db")
POOL_MIN = int(os.getenv("POOL_MIN", "1"))
POOL_MAX = int(os.getenv("POOL_MAX", "10"))
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("1", "true", "yes")
METRICS_PREFIX = os.getenv("METRICS_PREFIX", "intents_service")

# Configure structured JSON logging
logger = logging.getLogger("intents_service")
log_handler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

# Prometheus metrics (optional)
if PROMETHEUS_AVAILABLE and METRICS_ENABLED:
    REQUEST_COUNT = Counter(f"{METRICS_PREFIX}_http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
    REQUEST_LATENCY = Histogram(f"{METRICS_PREFIX}_http_request_latency_seconds", "HTTP request latency seconds", ["method", "endpoint"])  # noqa: E501
else:
    REQUEST_COUNT = None
    REQUEST_LATENCY = None

# FastAPI app and router
router = APIRouter(prefix="/intents", tags=["intents"])  # keep original prefix/tags
app = FastAPI(title="Intents Service", version="1.0.0")

# Mount optional prometheus metrics at /metrics when available
if PROMETHEUS_AVAILABLE and METRICS_ENABLED:
    try:
        metrics_app = make_asgi_app()
        app.mount("/metrics", metrics_app)
        logger.info("Prometheus metrics mounted at /metrics")
    except Exception as e:
        logger.exception("Failed to mount Prometheus metrics: %s", str(e))

# CORS policy (configure via env if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Graceful shutdown primitives
_shutdown_event = asyncio.Event()
_signal_handlers_installed = False


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown_cb: Callable[[], None]):
    global _signal_handlers_installed
    if _signal_handlers_installed:
        return

    def _handler(sig):
        logger.info("Received signal %s, initiating graceful shutdown", sig.name)
        try:
            # schedule shutdown callback as a task
            loop.create_task(shutdown_cb())
        except Exception:
            logger.exception("Error scheduling shutdown callback")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handler(s))
        except NotImplementedError:
            # Windows or restricted environments may not support add_signal_handler
            signal.signal(sig, lambda *_: logger.info("Signal received: %s", sig.name))

    _signal_handlers_installed = True


async def _shutdown_sequence():
    """Close DB pools and perform cleanup steps."""
    logger.info("Running shutdown sequence: closing store and setting shutdown event")
    # Close store/database pools if store exposes a close/shutdown function
    try:
        close_fn = getattr(store, "close", None) or getattr(store, "disconnect", None) or getattr(store, "shutdown", None)
        if close_fn is not None:
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            else:
                close_fn()
            logger.info("Store closed")
        else:
            logger.info("No store close method found; skipping DB pool shutdown")
    except Exception:
        logger.exception("Error while closing store")

    _shutdown_event.set()


# Middleware for logging and metrics
@app.middleware("http")
async def add_logging_and_metrics(request: Request, call_next):
    path = request.url.path
    method = request.method
    labels = {"method": method, "endpoint": path}
    logger.info("request_start", extra={"method": method, "path": path, "client": request.client.host if request.client else None})

    if REQUEST_LATENCY is not None:
        histogram = REQUEST_LATENCY.labels(method=method, endpoint=path)
        timer = histogram.time()
    else:
        timer = None

    try:
        response: Response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as exc:
        status_code = 500
        logger.exception("Unhandled exception while processing request: %s", str(exc))
        raise
    finally:
        if REQUEST_COUNT is not None:
            try:
                REQUEST_COUNT.labels(method=method, endpoint=path, http_status=str(status_code)).inc()
            except Exception:
                pass
        if timer is not None:
            try:
                timer.__exit__(None, None, None)  # stop histogram context
            except Exception:
                pass
        logger.info("request_end", extra={"method": method, "path": path, "status_code": status_code})


# Health and readiness endpoints
@app.get("/health", tags=["health"])
async def health():
    """Liveness probe - basic process health."""
    return JSONResponse({"status": "ok"})


@app.get("/ready", tags=["health"])
async def readiness():
    """Readiness probe - verifies DB connectivity / essential dependencies.

    The function will try to call store.ping() or store.is_healthy() if available.
    If the store exposes no such function, we assume readiness as long as startup completed.
    """
    # Prefer a dedicated ping/health function on the store
    try:
        ping_fn = getattr(store, "ping", None) or getattr(store, "is_healthy", None)
        if ping_fn is None:
            # If no ping is available, assume ready if we completed startup
            # (store init sets attribute _pool_initialized or similar? we check a best-effort attribute)
            pool_flag = getattr(store, "_pool_initialized", None)
            if pool_flag is True:
                return JSONResponse({"ready": True})
            else:
                # optimistic default: ready but add warning
                logger.warning("Readiness probe: no ping method on store and no _pool_initialized flag set; returning ready")
                return JSONResponse({"ready": True})

        if asyncio.iscoroutinefunction(ping_fn):
            ok = await ping_fn()
        else:
            ok = ping_fn()

        if ok:
            return JSONResponse({"ready": True})
        else:
            return JSONResponse({"ready": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse({"ready": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


# Original intents endpoints adapted to include monitoring/logging and consistent responses
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_intent(intent: Intent):
    """Create a new intent"""
    intent_dict = intent.model_dump(exclude={"id"})
    created = await store.add_intent(intent_dict)
    return created


@router.get("/")
async def read_intents():
    """Get all intents"""
    return await store.list_intents()


@router.get("/{intent_id}")
async def read_intent(intent_id: str):
    """Get a specific intent by ID"""
    intent_obj = await store.get_intent(intent_id)
    if intent_obj is None:
        return JSONResponse({"detail": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    return intent_obj


@router.put("/{intent_id}")
async def update_intent(intent_id: str, intent: Intent):
    """Update an intent"""
    intent_dict = intent.model_dump(exclude={"id"})
    await store.edit_intent(intent_id, intent_dict)
    return {"status": "success"}


@router.delete("/{intent_id}")
async def delete_intent(intent_id: str):
    """Delete an intent"""
    await store.delete_intent(intent_id)
    return {"status": "success"}


app.include_router(router)


# Lifespan events: initialize DB/connection pools and install signal handlers
@app.on_event("startup")
async def startup_event():
    logger.info("App startup: initializing store and other resources")

    # Initialize database connection pool if store provides an initializer
    try:
        # Common names for initializers: init_pool, init, connect, initialize
        init_fn = getattr(store, "init_pool", None) or getattr(store, "initialize", None) or getattr(store, "connect", None) or getattr(store, "startup", None)
        if init_fn is not None:
            # Prefer coroutine initializer
            kwargs = {"db_url": DB_URL, "min_size": POOL_MIN, "max_size": POOL_MAX}
            # Some store implementations may not accept kwargs; attempt to call gracefully
            if asyncio.iscoroutinefunction(init_fn):
                try:
                    await init_fn(DB_URL, min_size=POOL_MIN, max_size=POOL_MAX)
                except TypeError:
                    await init_fn(DB_URL)
            else:
                try:
                    init_fn(DB_URL, min_size=POOL_MIN, max_size=POOL_MAX)
                except TypeError:
                    init_fn(DB_URL)
            # Mark store as initialized if possible
            try:
                setattr(store, "_pool_initialized", True)
            except Exception:
                pass
            logger.info("Store initialized successfully")
        else:
            logger.warning("No store initializer found; skipping DB pool initialization")
    except Exception:
        logger.exception("Error initializing store; continuing startup (readiness may fail)")

    # Install signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    _install_signal_handlers(loop, _shutdown_sequence)
    logger.info("Signal handlers installed")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("App shutdown: invoking shutdown sequence")
    try:
        await _shutdown_sequence()
    except Exception:
        logger.exception("Error during shutdown sequence")


# If this file is run directly (for local testing), start uvicorn programmatically
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting uvicorn server at %s:%s", HOST, PORT)
    uvicorn.run("routes:app", host=HOST, port=PORT, log_level=LOG_LEVEL.lower(), reload=False)
