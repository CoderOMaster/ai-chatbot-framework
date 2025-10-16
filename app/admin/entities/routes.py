from fastapi import FastAPI, APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import os
import logging
import json
import asyncio
import signal
from typing import Optional

# Internal imports (unchanged)
from app.admin.entities import store
from app.admin.entities.schemas import Entity

# Environment
SERVICE_NAME = os.getenv("SERVICE_NAME", "entities-service")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
DB_URL = os.getenv("DB_URL", "")
DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
READINESS_ENABLED = os.getenv("READINESS_ENABLED", "true").lower() in ("1", "true", "yes")

# Structured JSON logger
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "service": SERVICE_NAME,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # include exception info if present
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # include extra fields if any
        if hasattr(record, "extra"):
            payload.update(record.extra)
        return json.dumps(payload)

logger = logging.getLogger(SERVICE_NAME)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

# Prometheus metrics (optional but included)
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total number of requests",
    ["method", "endpoint", "http_status"],
)
REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds",
    "Request latency",
    ["method", "endpoint"],
)

# FastAPI app and router
app = FastAPI(title=SERVICE_NAME)
router = APIRouter(prefix="/entities", tags=["entities"])

# Graceful shutdown event
shutdown_event = asyncio.Event()


# Utility wrappers for store lifecycle (store implementation is external)
async def _init_store():
    """Attempt to initialize the store with DB pooling settings.
    The store module is expected (optionally) to provide an async init/close interface:
      async def init(db_url: str, min_size: int, max_size: int)
      async def close()
    If those functions don't exist, this will log and continue.
    """
    if not DB_URL:
        logger.warning("No DB_URL provided; store initialization skipped")
        return

    try:
        init_fn = getattr(store, "init", None)
        if init_fn:
            # call async or sync init
            if asyncio.iscoroutinefunction(init_fn):
                await init_fn(DB_URL, min_size=DB_POOL_MIN_SIZE, max_size=DB_POOL_MAX_SIZE)
            else:
                init_fn(DB_URL, min_size=DB_POOL_MIN_SIZE, max_size=DB_POOL_MAX_SIZE)
            logger.info(json.dumps({"msg": "store initialized", "db_url": DB_URL}))
        else:
            logger.info("store has no init() function; assuming it manages its own connections")
    except Exception as e:
        logger.error(json.dumps({"msg": "store.init failed", "error": str(e)}))
        # Depending on your policy, you can raise here to stop startup
        # raise


async def _close_store():
    try:
        close_fn = getattr(store, "close", None)
        if close_fn:
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            else:
                close_fn()
            logger.info(json.dumps({"msg": "store closed"}))
        else:
            logger.info("store has no close() function; nothing to close")
    except Exception as e:
        logger.error(json.dumps({"msg": "store.close failed", "error": str(e)}))


# Instrumentation middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    endpoint = path
    with REQUEST_LATENCY.labels(method, endpoint).time():
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            REQUEST_COUNT.labels(method, endpoint, status_code).inc()
            return response
        except Exception as exc:
            # count 500s
            REQUEST_COUNT.labels(method, endpoint, "500").inc()
            logger.exception("Unhandled exception in request")
            raise


# Health and readiness endpoints
@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
async def health():
    """Liveness probe for Kubernetes / ECS.
    Should return 200 if the process is alive.
    """
    return PlainTextResponse(content="OK", status_code=200)


@app.get("/readiness", response_class=PlainTextResponse, include_in_schema=False)
async def readiness():
    """Readiness probe — should return 200 only if app is ready to serve traffic.
    We try to make a lightweight check against store if available.
    """
    if not READINESS_ENABLED:
        return PlainTextResponse(content="OK", status_code=200)

    check_fn = getattr(store, "health_check", None)
    try:
        if check_fn:
            # support async or sync
            if asyncio.iscoroutinefunction(check_fn):
                ok = await check_fn()
            else:
                ok = check_fn()
            return PlainTextResponse(content=("OK" if ok else "NOT_OK"), status_code=(200 if ok else 503))
        else:
            # no health_check available, fall back to OK if the store appears initialized
            # store may expose an attribute pool or connected
            connected = getattr(store, "connected", True)
            if connected:
                return PlainTextResponse(content="OK", status_code=200)
            else:
                return PlainTextResponse(content="NOT_OK", status_code=503)
    except Exception as e:
        logger.error(json.dumps({"msg": "readiness check failed", "error": str(e)}))
        return PlainTextResponse(content="NOT_OK", status_code=503)


# Prometheus metrics endpoint
@app.get("/metrics", include_in_schema=False)
async def metrics():
    content = generate_latest()
    return Response(content=content, media_type=CONTENT_TYPE_LATEST)


# Entities endpoints (refactored from original routes.py)
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_entity(entity: Entity):
    """Create a new entity"""
    entity_dict = entity.model_dump(exclude={"id"})
    try:
        result = await store.add_entity(entity_dict)
        logger.info(json.dumps({"msg": "entity_created", "entity": entity_dict}))
        return result
    except Exception as e:
        logger.error(json.dumps({"msg": "create_entity_failed", "error": str(e), "entity": entity_dict}))
        return JSONResponse(status_code=500, content={"error": "failed to create entity"})


@router.get("/")
async def read_entities():
    """Get all entities"""
    try:
        return await store.list_entities()
    except Exception as e:
        logger.error(json.dumps({"msg": "list_entities_failed", "error": str(e)}))
        return JSONResponse(status_code=500, content={"error": "failed to list entities"})


@router.get("/{entity_id}")
async def read_entity(entity_id: str):
    """Get a specific entity by ID"""
    try:
        entity = await store.get_entity(entity_id)
        if entity is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return entity
    except Exception as e:
        logger.error(json.dumps({"msg": "get_entity_failed", "error": str(e), "entity_id": entity_id}))
        return JSONResponse(status_code=500, content={"error": "failed to get entity"})


@router.put("/{entity_id}")
async def update_entity(entity_id: str, entity: Entity):
    """Update an entity"""
    entity_dict = entity.model_dump(exclude={"id"})
    try:
        await store.edit_entity(entity_id, entity_dict)
        logger.info(json.dumps({"msg": "entity_updated", "entity_id": entity_id}))
        return {"status": "success"}
    except Exception as e:
        logger.error(json.dumps({"msg": "update_entity_failed", "error": str(e), "entity_id": entity_id}))
        return JSONResponse(status_code=500, content={"error": "failed to update entity"})


@router.delete("/{entity_id}")
async def delete_entity(entity_id: str):
    """Delete an entity"""
    try:
        await store.delete_entity(entity_id)
        logger.info(json.dumps({"msg": "entity_deleted", "entity_id": entity_id}))
        return {"status": "success"}
    except Exception as e:
        logger.error(json.dumps({"msg": "delete_entity_failed", "error": str(e), "entity_id": entity_id}))
        return JSONResponse(status_code=500, content={"error": "failed to delete entity"})


# Register router
app.include_router(router)


# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    logger.info(json.dumps({"msg": "starting up"}))
    # initialize store (connection pooling etc.)
    await _init_store()

    # install SIGTERM handler to trigger graceful shutdown
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(_handle_sigterm()))
    except NotImplementedError:
        # signal handlers may not be available on Windows or some event loops
        logger.info(json.dumps({"msg": "signal handlers not available on this platform"}))


async def _handle_sigterm():
    logger.info(json.dumps({"msg": "SIGTERM received, starting graceful shutdown"}))
    # inform the system/service to stop routing traffic (readiness will fail if configured)
    # set event to allow background tasks to notice shutdown
    shutdown_event.set()
    # close store gracefully
    await _close_store()
    # give some time for in-flight requests to finish (tunable)
    await asyncio.sleep(float(os.getenv("GRACEFUL_SHUTDOWN_SECONDS", "5")))
    # then exit event loop: uvicorn/gunicorn will handle process termination


@app.on_event("shutdown")
async def shutdown_event_func():
    logger.info(json.dumps({"msg": "shutting down"}))
    await _close_store()


# If run directly, start uvicorn (useful for local dev)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.routes:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        # workers should be used in production via gunicorn + uvicorn workers
    )
