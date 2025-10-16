==> app/database.py
"""
Minimal database utilities and custom ObjectId field for Pydantic v2.
This module provides:
- ObjectIdField: pydantic-friendly wrapper around bson.ObjectId
- get_mongo_client / get_database: motor-based client with connection pooling

Note: If your repo already contains app.database, you can adapt this file or merge the helpers.
"""
from typing import Optional
import os
import logging

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
import bson
from pydantic import BaseModel

# pydantic v2 custom type hook
# Implement a lightweight wrapper so ObjectId values validate & serialize as string in JSON
class ObjectIdField(bson.ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        # Provides a validator to convert incoming values to ObjectId
        from pydantic import core_schema

        def _validate(v, info):
            if isinstance(v, bson.ObjectId):
                return v
            if isinstance(v, str):
                try:
                    return bson.ObjectId(v)
                except Exception as e:
                    raise ValueError(f"Invalid ObjectId: {e}")
            raise TypeError("ObjectId or its hex string is required")

        return core_schema.no_info_plain_validator_function(_validate)

    @classmethod
    def __get_pydantic_json_schema__(cls, handler):
        # Represent as string in generated JSON schema
        return {"type": "string", "format": "objectid"}

    def __str__(self) -> str:  # when converted to str, give hex
        return self.__repr__()

    def __repr__(self) -> str:
        return str(bson.ObjectId(self))


# Database client management
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "app_db")
MONGO_MAX_POOL_SIZE = int(os.getenv("MONGO_MAX_POOL_SIZE", "100"))

_logger = logging.getLogger(__name__)

_mongo_client: Optional[AsyncIOMotorClient] = None


def get_mongo_client() -> AsyncIOMotorClient:
    """Lazily create and return a Motor client with pooling options.
    This function is idempotent; it keeps a single global client instance.</n    """
    global _mongo_client
    if _mongo_client is None:
        _logger.info("Creating new Motor client (pool_size=%s)", MONGO_MAX_POOL_SIZE)
        _mongo_client = AsyncIOMotorClient(MONGO_URI, maxPoolSize=MONGO_MAX_POOL_SIZE)
    return _mongo_client


def get_database(name: Optional[str] = None):
    client = get_mongo_client()
    db_name = name or MONGO_DB
    return client[db_name]


async def ping_database() -> bool:
    """Try a small command to verify DB connectivity."""
    try:
        client = get_mongo_client()
        # admin command 'ping'
        await client.admin.command("ping")
        return True
    except PyMongoError:
        return False


async def close_mongo_client():
    global _mongo_client
    if _mongo_client is not None:
        _logger.info("Closing Motor client")
        _mongo_client.close()
        _mongo_client = None


# Expose constants for other modules
__all__ = ["ObjectIdField", "get_mongo_client", "get_database", "ping_database", "close_mongo_client"]


==> app/schemas.py
"""
Pydantic v2 schemas for Entity and EntityValue.
Original logic preserved, with model_config kept for arbitrary types.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List
from app.database import ObjectIdField


class EntityValue(BaseModel):
    """Schema for entity value"""

    value: str
    synonyms: List[str] = []


class Entity(BaseModel):
    """Schema for entity"""

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str
    entity_values: List[EntityValue] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


==> app/main.py
"""
FastAPI microservice wrapping the original schemas.
Provides:
- /health and /readiness endpoints
- Simple CRUD for /entities (demonstration)
- Structured JSON logging
- Graceful SIGTERM handling
- Connection pooling via motor
- /metrics endpoint for Prometheus

Save this package as a module and run with uvicorn: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import os
import sys
import signal
import asyncio
import logging
import json
from typing import List

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# structured logging
from pythonjsonlogger import jsonlogger

from app.schemas import Entity, EntityValue
from app.database import get_database, ping_database, close_mongo_client, get_mongo_client
from app.database import ObjectIdField

# Environment configuration
SERVICE_NAME = os.getenv("SERVICE_NAME", "entities-service")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_JSON = os.getenv("LOG_JSON", "true").lower() in ("1", "true", "yes")

# Configure logging (JSON structured)
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
log_handler = logging.StreamHandler(sys.stdout)
if LOG_JSON:
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
else:
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler.setFormatter(formatter)
logger.handlers = [log_handler]

app = FastAPI(title=SERVICE_NAME)

# CORS (optional)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Latency per HTTP request", ["endpoint"]) 


def record_metrics(method: str, endpoint: str, status_code: int, latency: float):
    try:
        REQUEST_COUNT.labels(method, endpoint, status_code).inc()
        REQUEST_LATENCY.labels(endpoint).observe(latency)
    except Exception:
        logger.exception("Failed to record metrics")


# Dependency: get MongoDB collection
def get_entities_collection():
    db = get_database()
    return db.entities


@app.on_event("startup")
async def startup_event():
    logger.info("Starting %s", SERVICE_NAME)
    # Eagerly create client instance with pooling
    get_mongo_client()
    # register signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown("SIGTERM")))
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown("SIGINT")))
    except NotImplementedError:
        # loop.add_signal_handler not implemented on Windows event loop
        logger.debug("Signal handlers not installed (platform limitation)")


async def shutdown(sig: str = None):
    logger.warning("Received exit signal %s, shutting down...", sig)
    await close_mongo_client()
    # allow some time for graceful shutdown
    await asyncio.sleep(0.1)
    # uvicorn will exit after cleanup


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutdown event: closing DB client")
    await close_mongo_client()


@app.get("/health")
async def health():
    """Liveness probe: simple service-level check."""
    return JSONResponse(status_code=200, content={"status": "ok", "service": SERVICE_NAME})


@app.get("/readiness")
async def readiness():
    """Readiness probe: check DB connectivity."""
    ok = await ping_database()
    if not ok:
        logger.warning("Readiness probe: DB ping failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable")
    return JSONResponse(status_code=200, content={"status": "ready"})


@app.post("/entities", response_model=Entity, status_code=status.HTTP_201_CREATED)
async def create_entity(entity: Entity, collection=Depends(get_entities_collection)):
    import time
    start = time.time()
    doc = entity.model_dump()  # pydantic v2
    # convert id field name
    if doc.get("id") is None:
        doc.pop("id", None)
    # save
    res = await collection.insert_one({"name": doc["name"], "entity_values": doc.get("entity_values", [])})
    inserted = await collection.find_one({"_id": res.inserted_id})
    # convert _id to id in response
    inserted["id"] = str(inserted.get("_id"))
    inserted.pop("_id", None)
    elapsed = time.time() - start
    record_metrics("POST", "/entities", 201, elapsed)
    return inserted


@app.get("/entities", response_model=List[Entity])
async def list_entities(limit: int = 50, collection=Depends(get_entities_collection)):
    import time
    start = time.time()
    cursor = collection.find().limit(min(limit, 100))
    docs = []
    async for d in cursor:
        d["id"] = str(d.get("_id"))
        d.pop("_id", None)
        docs.append(d)
    elapsed = time.time() - start
    record_metrics("GET", "/entities", 200, elapsed)
    return docs


@app.get("/metrics")
async def metrics():
    # Expose prometheus metrics
    content = generate_latest()
    return PlainTextResponse(content.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


# Basic root
@app.get("/")
async def root():
    return {"service": SERVICE_NAME}


if __name__ == "__main__":
    # For local development only; in production prefer `uvicorn`/k8s probes
    uvicorn.run("app.main:app", host="0.0.0.0", port=LISTEN_PORT, log_level=LOG_LEVEL.lower())
