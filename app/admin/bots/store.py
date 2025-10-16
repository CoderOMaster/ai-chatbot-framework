from typing import Dict, Optional
import os
import asyncio
import logging
import signal
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Internal application imports (kept as-is)
from app.admin.bots.schemas import Bot, NLUConfiguration
from app.admin.entities.store import list_entities, bulk_import_entities
from app.admin.intents.store import list_intents, bulk_import_intents
import app.database as app_database  # monkeypatching this module at startup

# Async MongoDB driver
from motor.motor_asyncio import AsyncIOMotorClient

# Optional metrics
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    METRICS_AVAILABLE = True
except Exception:
    METRICS_AVAILABLE = False

# Structured JSON logging
from pythonjsonlogger import jsonlogger

# Environment configuration with sensible defaults
ENV = os.getenv("APP_ENV", "production")
DB_URL = os.getenv("DB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "mydb")
DB_MAX_POOL_SIZE = int(os.getenv("DB_MAX_POOL_SIZE", "50"))
DB_MIN_POOL_SIZE = int(os.getenv("DB_MIN_POOL_SIZE", "0"))
SERVICE_PORT = int(os.getenv("PORT", "8000"))
ENABLE_METRICS = os.getenv("ENABLE_METRICS", "false").lower() in ("1", "true", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Application
app = FastAPI(title="Bot Store Service", version="1.0.0")

# CORS (optional, can be adjusted via env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGIN", "*")],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Setup JSON structured logging
logger = logging.getLogger("bot_store_service")
log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d'
)
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(LOG_LEVEL)

# Simple Prometheus instrumentation (optional)
if METRICS_AVAILABLE and ENABLE_METRICS:
    REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
    REQUEST_LATENCY = Histogram("http_request_latency_seconds", "HTTP request latency", ["endpoint"])  # type: ignore
else:
    # Dummy objects to avoid checks all over the code
    class _Noop:
        def labels(self, *a, **k):
            return self

        def inc(self, *a, **k):
            pass

        def observe(self, *a, **k):
            pass

    REQUEST_COUNT = _Noop()
    REQUEST_LATENCY = _Noop()


# Health models
class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


# Graceful shutdown helper
shutdown_event = asyncio.Event()


async def _create_motor_client():
    """Create motor client with connection pooling options and monkeypatch app.database.

    We create the client here and set attributes on the imported app.database module
    so existing internal modules that import app.database will use the same client / database.
    """
    logger.info("creating motor client", extra={"db_url": DB_URL, "db_name": DB_NAME})
    # Configure pooling
    client = AsyncIOMotorClient(
        DB_URL,
        maxPoolSize=DB_MAX_POOL_SIZE,
        minPoolSize=DB_MIN_POOL_SIZE,
        serverSelectionTimeoutMS=5000,
    )

    db = client[DB_NAME]

    # Monkeypatch the imported app.database module so shared internal modules use the same connection
    try:
        setattr(app_database, "client", client)
        setattr(app_database, "database", db)
    except Exception as e:
        # If app.database structure differs, log warning and continue
        logger.warning("could not monkeypatch app.database module", extra={"error": str(e)})

    return client, db


@app.on_event("startup")
async def startup_event():
    """Startup tasks: connect to DB and ensure default bot exists. Register signal handlers for graceful shutdown."""
    app.state.mongo_client, app.state.db = await _create_motor_client()

    # Obtain collection used in this module
    app.state.bot_collection = app.state.db.get_collection("bot")

    # attempt to ensure default bot exists (mirrors original behavior)
    try:
        # reuse original ensure_default_bot logic but adapted to use local collection
        default_bot = await app.state.bot_collection.find_one({"name": "default"})
        if default_bot is None:
            default_bot_data = Bot(name="default")
            default_bot_data.created_at = datetime.utcnow()
            default_bot_data.updated_at = datetime.utcnow()
            await app.state.bot_collection.insert_one(default_bot_data.model_dump(exclude={"id": True}))
            logger.info("created default bot")
        else:
            logger.info("default bot already exists")
    except Exception as exc:
        logger.exception("failed to ensure default bot on startup", exc_info=exc)

    # Register signal handlers to set shutdown event (helps graceful shutdown in some runners)
    loop = asyncio.get_running_loop()

    def _on_signal(sig):
        logger.info("received signal, setting shutdown_event", extra={"signal": str(sig)})
        try:
            shutdown_event.set()
        except Exception:
            pass

    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: _on_signal("SIGTERM"))
        loop.add_signal_handler(signal.SIGINT, lambda: _on_signal("SIGINT"))
    except NotImplementedError:
        # add_signal_handler not implemented on Windows loop policy
        logger.debug("loop.add_signal_handler not implemented on this platform")


@app.on_event("shutdown")
async def shutdown_event_func():
    """Shutdown tasks: close DB client."""
    logger.info("shutting down, closing db client")
    try:
        client: AsyncIOMotorClient = getattr(app.state, "mongo_client", None)
        if client is not None:
            client.close()
            logger.info("db client closed")
    except Exception as exc:
        logger.exception("error closing db client", exc_info=exc)


# Middleware for metrics and logging
@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    endpoint = path
    start = asyncio.get_event_loop().time()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        logger.exception("unhandled error in request", exc_info=exc, extra={"path": path, "method": method})
        raise
    finally:
        latency = asyncio.get_event_loop().time() - start
        try:
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(status_code)).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint).observe(latency)
        except Exception:
            # Ignore metrics errors
            pass
    return response


# Health endpoints
@app.get("/health", response_model=HealthResponse)
async def health():
    resp = HealthResponse(status="ok", timestamp=datetime.utcnow())
    return resp


@app.get("/readiness")
async def readiness():
    """Readiness: attempt a fast DB ping to verify connectivity."""
    try:
        client: AsyncIOMotorClient = getattr(app.state, "mongo_client")
        # motor uses admin.command
        await client.admin.command("ping")
        return JSONResponse(status_code=200, content={"ready": True})
    except Exception as exc:
        logger.warning("readiness check failed", extra={"error": str(exc)})
        return JSONResponse(status_code=503, content={"ready": False, "error": str(exc)})


# Expose /metrics if prometheus is enabled
if METRICS_AVAILABLE and ENABLE_METRICS:
    @app.get("/metrics")
    async def metrics():
        try:
            data = generate_latest()
            return JSONResponse(content=data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
        except Exception as exc:
            logger.exception("error generating metrics", exc_info=exc)
            raise HTTPException(status_code=500, detail="metrics unavailable")


# Helper to get bot collection (keeps original module's function semantics)
def _bot_collection():
    return getattr(app.state, "bot_collection")


# Replicated original functions as HTTP endpoints
@app.get("/bot/{name}")
async def api_get_bot(name: str):
    coll = _bot_collection()
    bot_doc = await coll.find_one({"name": name})
    if not bot_doc:
        raise HTTPException(status_code=404, detail=f"bot '{name}' not found")
    bot = Bot.model_validate(bot_doc)
    return JSONResponse(content=bot.model_dump())


@app.get("/bot/{name}/nlu")
async def api_get_nlu_config(name: str):
    coll = _bot_collection()
    bot_doc = await coll.find_one({"name": name})
    if not bot_doc:
        raise HTTPException(status_code=404, detail=f"bot '{name}' not found")
    bot = Bot.model_validate(bot_doc)
    nlu = bot.nlu_config if hasattr(bot, "nlu_config") else None
    return JSONResponse(content={"nlu_config": nlu})


@app.put("/bot/{name}/nlu")
async def api_update_nlu_config(name: str, nlu_config: dict):
    coll = _bot_collection()
    result = await coll.update_one({"name": name}, {"$set": {"nlu_config": nlu_config}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"bot '{name}' not found")
    return JSONResponse(status_code=200, content={"updated": True})


@app.get("/bot/{name}/export")
async def api_export_bot(name: str):
    # The original export ignored name and exported global intents/entities; preserve behavior
    try:
        intents = await list_intents()
        entities = await list_entities()

        entities_dump = [entity.model_dump(exclude={"id"}) for entity in entities]
        intents_dump = [
            intent.model_dump(exclude={"id": True, "parameters": {"__all__": {"id"}}})
            for intent in intents
        ]

        export_data = {"intents": intents_dump, "entities": entities_dump}
        return JSONResponse(status_code=200, content=export_data)
    except Exception as exc:
        logger.exception("export failed", exc_info=exc)
        raise HTTPException(status_code=500, detail="export failed")


@app.post("/bot/{name}/import")
async def api_import_bot(name: str, data: Dict):
    # The original import ignored name for created resources; preserve behavior
    try:
        intents = data.get("intents", [])
        entities = data.get("entities", [])

        created_intents = await bulk_import_intents(intents)
        created_entities = await bulk_import_entities(entities)

        return JSONResponse(
            status_code=201,
            content={
                "num_intents_created": len(created_intents),
                "num_entities_created": len(created_entities),
            },
        )
    except Exception as exc:
        logger.exception("import failed", exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc))


# Provide a lightweight root
@app.get("/")
async def root():
    return {"service": "bot-store", "env": ENV}


# Run app with uvicorn externally; include a programmatic entrypoint for local dev
def run():
    import uvicorn

    uvicorn.run("store:app", host="0.0.0.0", port=SERVICE_PORT, log_level=LOG_LEVEL.lower())


if __name__ == "__main__":
    run()
