import os
import asyncio
import signal
import logging
import json
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseSettings
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# Internal models (unchanged namespace from project)
from app.admin.integrations.schemas import Integration, IntegrationUpdate


class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "appdb"
    MONGO_MAX_POOL_SIZE: int = 100
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    METRICS_ENABLED: bool = True

    class Config:
        env_file = ".env"


settings = Settings()


# Structured JSON logging setup
class JSONLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        # include extra fields if present
        if hasattr(record, "extra"):
            try:
                log_record.update(record.extra)
            except Exception:
                pass
        return json.dumps(log_record)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter())

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    # remove default handlers
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)

    # uvicorn loggers
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.error").handlers = [handler]


setup_logging()
logger = logging.getLogger("integrations_service")


# Prometheus metrics
REQUESTS_COUNTER = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status"])
DB_QUERIES = Counter("db_queries_total", "Total DB queries executed")
ERRORS = Counter("http_errors_total", "Total HTTP errors", ["path"])


app = FastAPI(title="Integrations Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

collection_name = "integrations"


# Middleware to instrument requests and log
@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    try:
        response: Response = await call_next(request)
        status_code = response.status_code
        if settings.METRICS_ENABLED:
            REQUESTS_COUNTER.labels(method=method, path=path, status=status_code).inc()
        logger.info(f"request complete", extra={"extra": {"method": method, "path": path, "status": status_code}})
        return response
    except Exception as exc:
        if settings.METRICS_ENABLED:
            ERRORS.labels(path=path).inc()
        logger.exception("Unhandled request error", extra={"extra": {"method": method, "path": path}})
        raise


@app.on_event("startup")
async def startup_event():
    """Create Mongo client with connection pooling and ensure defaults."""
    # Create Motor client with pool options
    logger.info("starting up integrations service")
    try:
        app.state.mongo_client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            maxPoolSize=int(settings.MONGO_MAX_POOL_SIZE),
            tz_aware=True,
        )
        # Database handle
        app.state.db = app.state.mongo_client[settings.MONGODB_DB]

        # Ensure DB reachable
        DB_PING = {"ping": 1}
        await app.state.db.command(DB_PING)
        logger.info("connected to mongodb", extra={"extra": {"db": settings.MONGODB_DB}})

        # Ensure default integrations exist
        await ensure_default_integrations()

        # Register a SIGTERM handler to gracefully shutdown DB
        loop = asyncio.get_running_loop()

        def _sigterm_handler() -> None:
            logger.info("SIGTERM received, scheduling shutdown")
            # schedule shutdown tasks
            asyncio.create_task(_graceful_shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _sigterm_handler)
            except NotImplementedError:
                # Not available on every platform (e.g., Windows event loop)
                pass

    except Exception:
        logger.exception("failed during startup")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("shutting down integrations service")
    client: Optional[AsyncIOMotorClient] = getattr(app.state, "mongo_client", None)
    if client:
        client.close()
        logger.info("mongodb connection closed")


async def _graceful_shutdown():
    """Close DB and stop loop after a short wait to let current requests finish."""
    client: Optional[AsyncIOMotorClient] = getattr(app.state, "mongo_client", None)
    if client:
        try:
            client.close()
            logger.info("mongodb connection closed (signal handler)")
        except Exception:
            logger.exception("error closing mongodb client")
    # let uvicorn manage process exit; nothing else needed here


# Data access functions (adapted from original store.py)
async def list_integrations() -> List[Integration]:
    """Get all integrations."""
    DB_QUERIES.inc()
    cursor = app.state.db[collection_name].find()
    integrations = await cursor.to_list(length=None)
    return [Integration(**integration) for integration in integrations]


async def get_integration(id: str) -> Optional[Integration]:
    """Get a specific integration by ID."""
    DB_QUERIES.inc()
    integration = await app.state.db[collection_name].find_one({"id": id})
    if integration:
        return Integration(**integration)
    return None


async def update_integration_store(id: str, integration_update: IntegrationUpdate) -> Optional[Integration]:
    """Update an integration's status and settings."""
    DB_QUERIES.inc()
    update_data = integration_update.model_dump(exclude_unset=True)

    result = await app.state.db[collection_name].find_one_and_update(
        {"id": id},
        {"$set": update_data},
        return_document=ReturnDocument.AFTER,
    )

    if result:
        return Integration(**result)
    return None


async def ensure_default_integrations():
    """Ensure default integrations exist in the database."""
    DB_QUERIES.inc()
    default_integrations = [
        {
            "id": "facebook",
            "name": "Facebook Messenger",
            "description": "Connect with Facebook Messenger",
            "status": False,
            "settings": {
                "verify": "ai-chatbot-framework",
                "secret": "",
                "page_access_token": "",
            },
        },
        {
            "id": "chat_widget",
            "name": "Chat Widget",
            "description": "Add a chat widget to your website",
            "status": True,
            "settings": {},
        },
    ]

    # Use upsert with $setOnInsert
    tasks = []
    for integration in default_integrations:
        tasks.append(
            app.state.db[collection_name].update_one(
                {"id": integration["id"]}, {"$setOnInsert": integration}, upsert=True
            )
        )

    if tasks:
        await asyncio.gather(*tasks)
        logger.info("ensured default integrations")


# HTTP Endpoints
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/readiness")
async def readiness():
    # check DB connectivity
    try:
        await app.state.db.command({"ping": 1})
        return {"ready": True}
    except Exception:
        logger.exception("readiness check failed")
        raise HTTPException(status_code=503, detail="database unreachable")


@app.get("/integrations", response_model=List[Integration])
async def http_list_integrations():
    integrations = await list_integrations()
    return integrations


@app.get("/integrations/{integration_id}", response_model=Integration)
async def http_get_integration(integration_id: str):
    integration = await get_integration(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="integration not found")
    return integration


@app.patch("/integrations/{integration_id}", response_model=Integration)
async def http_update_integration(integration_id: str, payload: IntegrationUpdate):
    updated = await update_integration_store(integration_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="integration not found")
    return updated


@app.post("/integrations/ensure-defaults", status_code=status.HTTP_204_NO_CONTENT)
async def http_ensure_defaults():
    await ensure_default_integrations()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/metrics")
async def metrics_endpoint():
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="metrics disabled")
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "__main__:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=False,
    )
