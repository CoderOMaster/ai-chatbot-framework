import os
import sys
import signal
import logging
from logging.config import dictConfig
from typing import Dict, Optional, List
import asyncio

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Optional async SQLAlchemy for connection pooling
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.exc import OperationalError

# -----------------------------
# Schemas (refactored from original schemas.py)
# -----------------------------

class IntegrationBase(BaseModel):
    id: str
    name: str
    description: str
    status: bool = False
    # NOTE: original used a mutable default {} which can be unsafe. We default to None.
    settings: Optional[Dict] = None


class IntegrationCreate(IntegrationBase):
    pass


class IntegrationUpdate(IntegrationBase):
    pass


class Integration(IntegrationBase):
    class Config:
        # Keep compat with pydantic usage. If you rely on ORM attributes
        # consumers may set orm_mode=True in their own models or adapters.
        # from_attributes exists in pydantic v2; if using v1, consider orm_mode.
        from_attributes = True

# -----------------------------
# Configuration from environment
# -----------------------------

APP_NAME = os.getenv("APP_NAME", "integration-service")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")
DATABASE_URL = os.getenv("DATABASE_URL")  # expected async URL for SQLAlchemy, e.g. postgresql+asyncpg://...
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", 5))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", 10))
READINESS_TIMEOUT = int(os.getenv("READINESS_TIMEOUT", 5))

# -----------------------------
# Structured JSON logging setup
# -----------------------------

def setup_logging():
    logger = logging.getLogger()
    logger.handlers = []
    log_handler = logging.StreamHandler(sys.stdout)
    fmt = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    log_handler.setFormatter(fmt)
    logger.addHandler(log_handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


setup_logging()
logger = logging.getLogger(APP_NAME)

# -----------------------------
# Prometheus metrics
# -----------------------------

REQUEST_COUNT = Counter(
    'http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'http_status']
)
REQUEST_LATENCY = Histogram('http_request_latency_seconds', 'Request latency', ['endpoint'])

# -----------------------------
# FastAPI app and state
# -----------------------------

app = FastAPI(title=APP_NAME)

# allow CORS for flexibility in microservices environments; tune in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for Integration objects (keeps original program logic while running as microservice)
# NOTE: For production you should implement persistence to a database.
_store: Dict[str, Integration] = {}

# Async DB engine (optional)
_db_engine: Optional[AsyncEngine] = None
_ready = False
_shutdown_in_progress = False

# -----------------------------
# Middleware for logging & metrics
# -----------------------------

@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    endpoint = path
    with REQUEST_LATENCY.labels(endpoint=endpoint).time():
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(status_code)).inc()

# -----------------------------
# Health & readiness endpoints
# -----------------------------

@app.get("/health")
async def health():
    """Liveness probe endpoint. Returns 200 as long as process is running."""
    return {"status": "ok", "app": APP_NAME}


@app.get("/readiness")
async def readiness():
    """Readiness probe. Checks whether startup completed and DB connection (if configured) is ready."""
    global _ready, _db_engine
    if not _ready:
        logger.warning("Readiness probe: not ready")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not ready")

    # If DB is configured, check a simple connection
    if _db_engine is not None:
        try:
            async with _db_engine.begin() as conn:
                # run a trivial statement depending on DB (Postgres supports SELECT 1)
                await conn.exec_driver_sql("SELECT 1")
        except Exception as e:
            logger.exception("Readiness check failed: DB not available: %s", e)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db not ready")

    return {"status": "ready"}

# Prometheus metrics endpoint
@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# -----------------------------
# CRUD endpoints (in-memory for example)
# -----------------------------

@app.post("/integrations", response_model=Integration, status_code=status.HTTP_201_CREATED)
async def create_integration(payload: IntegrationCreate):
    if payload.id in _store:
        raise HTTPException(status_code=400, detail="integration id already exists")
    # If settings is None, default to empty dict to preserve original behavior
    if payload.settings is None:
        payload.settings = {}
    integration = Integration(**payload.dict())
    _store[integration.id] = integration
    logger.info("Created integration", extra={"id": integration.id})
    return integration


@app.get("/integrations", response_model=List[Integration])
async def list_integrations():
    return list(_store.values())


@app.get("/integrations/{integration_id}", response_model=Integration)
async def get_integration(integration_id: str):
    item = _store.get(integration_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    return item


@app.put("/integrations/{integration_id}", response_model=Integration)
async def update_integration(integration_id: str, payload: IntegrationUpdate):
    if integration_id not in _store:
        raise HTTPException(status_code=404, detail="not found")
    if payload.settings is None:
        payload.settings = {}
    updated = Integration(**payload.dict())
    _store[integration_id] = updated
    logger.info("Updated integration", extra={"id": integration_id})
    return updated


@app.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(integration_id: str):
    if integration_id not in _store:
        raise HTTPException(status_code=404, detail="not found")
    del _store[integration_id]
    logger.info("Deleted integration", extra={"id": integration_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# -----------------------------
# Startup & shutdown lifecycle
# -----------------------------

async def _init_db_engine():
    global _db_engine
    if not DATABASE_URL:
        logger.info("No DATABASE_URL configured; skipping DB engine initialization")
        return

    try:
        # create_async_engine requires an async driver in the URL (eg: postgresql+asyncpg://)
        _db_engine = create_async_engine(
            DATABASE_URL,
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_timeout=30,
            echo=(LOG_LEVEL == "DEBUG"),
            future=True,
        )
        # test connection
        async with _db_engine.begin() as conn:
            await conn.exec_driver_sql("SELECT 1")
        logger.info("DB engine initialized and tested")
    except Exception as e:
        logger.exception("Failed to initialize DB engine: %s", e)
        # Re-raise so startup fails if DB is mandatory; if optional, you can set _db_engine = None
        raise


@app.on_event("startup")
async def on_startup():
    global _ready
    logger.info("Starting %s", APP_NAME)
    # Install signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def _on_sigterm(signum, frame):
        global _shutdown_in_progress
        if _shutdown_in_progress:
            return
        _shutdown_in_progress = True
        logger.info("Received SIGTERM (or SIGINT). Initiating graceful shutdown...", extra={"signal": signum})
        # Mark not ready immediately so orchestrator stops sending traffic
        try:
            # Can't await here; schedule shutdown tasks on loop
            asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        except Exception:
            logger.exception("Failed to schedule shutdown task")

    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)

    # Initialize DB if configured
    try:
        if DATABASE_URL:
            await _init_db_engine()
    except Exception:
        # If DB initialization fails at startup, we should not mark ready. Let exception bubble.
        logger.exception("Database initialization failed during startup")
        raise

    # Simple delay to allow other dependencies to warm up if desired
    await asyncio.sleep(0)
    _ready = True
    logger.info("Startup complete. Application is ready.")


async def _shutdown():
    global _ready, _db_engine
    logger.info("Shutdown sequence started")
    _ready = False
    # give some time for in-flight requests
    await asyncio.sleep(0.5)
    if _db_engine is not None:
        try:
            await _db_engine.dispose()
            logger.info("DB engine disposed")
        except Exception:
            logger.exception("Error while disposing DB engine")
    logger.info("Shutdown sequence complete. Exiting.")
    # Exit the process; uvicorn should stop the server loop after cleanup
    os._exit(0)


@app.on_event("shutdown")
async def on_shutdown():
    # Called by server on graceful shutdown
    logger.info("on_shutdown called by ASGI server")
    await _shutdown()

# -----------------------------
# Run with Uvicorn when executed directly
# -----------------------------

if __name__ == "__main__":
    import uvicorn

    # Use uvicorn's programmatic API to run app
    uvicorn.run(
        "__main__:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        # use multiprocessing in K8s/ECS via replica count rather than uvicorn workers
    )
