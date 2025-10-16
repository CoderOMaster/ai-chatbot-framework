'''File: routes.py
A self-contained FastAPI microservice router and application entry for Kubernetes/Fargate
- Provides /integrations endpoints (list/get/update) using the existing internal store and schemas
- Adds /health and /readiness
- Structured JSON logging
- Uses environment variables
- Graceful startup/shutdown and SIGTERM handling
- Hooks for connection pooling initialization and teardown in the store module
- Prometheus metrics endpoint and simple request metrics

Note: This file expects internal modules at:
  app.admin.integrations.store
  app.admin.integrations.schemas
which should provide the same async functions used previously.
'''

import os
import sys
import time
import asyncio
import signal
import logging
from typing import List, Optional

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# Internal imports (unchanged logic locations from original code)
from app.admin.integrations import store
from app.admin.integrations.schemas import Integration, IntegrationUpdate

# Observability
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Structured logging
from pythonjsonlogger import jsonlogger

# Environment configuration with sensible defaults
APP_NAME = os.getenv("APP_NAME", "integrations-service")
ENVIRONMENT = os.getenv("ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
DB_DSN = os.getenv("DB_DSN", "")  # if your store needs a connection string
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("1", "true", "yes")

# Configure structured JSON logger
logger = logging.getLogger(APP_NAME)
logger.setLevel(LOG_LEVEL)

if not logger.handlers:
    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s %(filename)s %(lineno)d')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logger = logger.bind if hasattr(logger, 'bind') else logger  # type: ignore

# Prometheus metrics (basic)
REQUEST_COUNT = Counter(
    'http_requests_total', 'Total HTTP requests', ['method', 'path', 'status']
)
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['method', 'path'])

# Create FastAPI app
app = FastAPI(title=APP_NAME, version="1.0.0")
router = APIRouter(prefix="/integrations", tags=["integrations"])

# CORS (optional - adjust in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOW_ORIGINS", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware for logging and metrics
@app.middleware("http")
async def log_and_measure(request: Request, call_next):
    start = time.time()
    path = request.url.path
    method = request.method
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        # Count as 500 and re-raise
        REQUEST_COUNT.labels(method=method, path=path, status="500").inc()
        logger.error({"event": "request_error", "method": method, "path": path, "error": str(e)})
        raise
    finally:
        elapsed = time.time() - start
        if METRICS_ENABLED:
            try:
                REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)
                REQUEST_COUNT.labels(method=method, path=path, status=str(response.status_code if 'response' in locals() else 500)).inc()
            except Exception:
                # metrics should not break the request
                pass
        # Structured log for request
        logger.info({
            "event": "http_request",
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "duration": elapsed,
            "env": ENVIRONMENT,
        })

    return response


# Health endpoints
@app.get("/health", include_in_schema=False)
async def health():
    """Liveness probe."""
    return JSONResponse({"status": "ok", "app": APP_NAME})


@app.get("/readiness", include_in_schema=False)
async def readiness():
    """Readiness probe. Check DB connection / store readiness if available."""
    # If store exposes a ping or is_ready method, call it. This is optional and non-blocking.
    check = {"db": "unknown"}
    try:
        if hasattr(store, 'is_ready'):
            ready = await getattr(store, 'is_ready')()
            check['db'] = 'ready' if ready else 'not_ready'
        elif hasattr(store, 'ping'):
            pong = await getattr(store, 'ping')()
            check['db'] = 'ready' if pong else 'not_ready'
        elif DB_DSN:
            # If store has no explicit ping, but DB_DSN is set, assume ready and let app handle errors during ops
            check['db'] = 'unchecked'
        else:
            check['db'] = 'unconfigured'
    except Exception as ex:
        logger.error({"event": "readiness_check_failed", "error": str(ex)})
        return JSONResponse(status_code=503, content={"ready": False, "checks": check})

    return JSONResponse({"ready": True, "checks": check})


# Integrations routes (original logic preserved)
@router.get("/", response_model=List[Integration])
async def list_integrations():
    """List all available integrations."""
    return await store.list_integrations()


@router.get("/{id}", response_model=Integration)
async def get_integration(id: str):
    """Get a specific integration by ID."""
    integration = await store.get_integration(id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.put("/{id}", response_model=Integration)
async def update_integration(id: str, integration: IntegrationUpdate):
    """Update an integration's status and settings."""
    updated_integration = await store.update_integration(id, integration)
    if not updated_integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return updated_integration


app.include_router(router)


# Optional metrics endpoint
if METRICS_ENABLED:
    @app.get('/metrics')
    async def metrics():
        resp = generate_latest()
        return Response(content=resp, media_type=CONTENT_TYPE_LATEST)


# Lifecycle events: initialize/close DB pools and other resources
@app.on_event("startup")
async def startup_event():
    logger.info({"event": "startup", "env": ENVIRONMENT, "db_dsn_present": bool(DB_DSN)})
    # If store implements a connection pool initializer, call it.
    try:
        if DB_DSN and hasattr(store, 'init_pool'):
            # init_pool signature: async def init_pool(dsn: str, max_size: int = 10):
            max_pool = int(os.getenv('DB_MAX_POOL', '10'))
            await getattr(store, 'init_pool')(DB_DSN, max_pool)
            logger.info({"event": "db_pool_initialized", "max_pool": max_pool})
        elif DB_DSN and hasattr(store, 'connect'):
            await getattr(store, 'connect')(DB_DSN)
            logger.info({"event": "db_connected"})
        else:
            logger.info({"event": "db_pool_not_configured"})
    except Exception as ex:
        logger.exception({"event": "db_init_failed", "error": str(ex)})
        # If DB is critical, fail startup by re-raising
        if os.getenv('REQUIRE_DB_ON_STARTUP', 'false').lower() in ('1', 'true', 'yes'):
            raise


@app.on_event("shutdown")
async def shutdown_event():
    logger.info({"event": "shutdown"})
    # Close DB pool if available
    try:
        if hasattr(store, 'close_pool'):
            await getattr(store, 'close_pool')()
            logger.info({"event": "db_pool_closed"})
        elif hasattr(store, 'disconnect'):
            await getattr(store, 'disconnect')()
            logger.info({"event": "db_disconnected"})
    except Exception as ex:
        logger.exception({"event": "db_close_failed", "error": str(ex)})


# Graceful shutdown on SIGTERM for non-uvicorn managed environments
def _cancel_tasks(loop):
    to_cancel = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not to_cancel:
        return
    for task in to_cancel:
        task.cancel()


def _handle_sigterm():
    """Signal handler to attempt graceful shutdown of the asyncio loop."""
    loop = asyncio.get_event_loop()
    logger.info({"event": "sigterm_received", "message": "Initiating graceful shutdown"})
    _cancel_tasks(loop)


# Register signal handlers only if running as main and the platform supports it
if sys.platform != 'win32':
    try:
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
    except Exception:
        # Not fatal - uvicorn / gunicorn normally handles this
        pass


# If this module is executed directly, run uvicorn for local debugging/container entrypoint convenience
if __name__ == '__main__':
    import uvicorn

    uvicorn.run(
        'routes:app',
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        # When deployed in k8s you typically run one worker per container and scale with replicas
        # For local debugging this single-process server is sufficient
    )
