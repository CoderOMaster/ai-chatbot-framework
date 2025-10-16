import os
import asyncio
import signal
import logging
import json
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from bson import ObjectId
import structlog
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# Keep the original Entity import (app.admin.entities.schemas) if available.
# The refactor expects that module to exist and provide Entity with model_validate.
try:
    from app.admin.entities.schemas import Entity
except Exception:  # pragma: no cover - fall back if internal package isn't present at dev time
    # Minimal fallback Entity model for local development / tests. Keeps same API surface used by code.
    class Entity(BaseModel):
        id: Optional[str] = None
        name: Optional[str] = None
        entity_values: List[Dict] = []

        @classmethod
        def model_validate(cls, raw):
            if not raw:
                return None
            # Convert MongoDB _id to id
            raw = dict(raw)
            if raw.get("_id"):
                raw["id"] = str(raw["_id"])
                raw.pop("_id", None)
            return cls(**raw)

# ---- Configuration via environment variables ----
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "defaultdb")
MAX_POOL_SIZE = int(os.getenv("MAX_POOL_SIZE", "100"))
SERVICE_HOST = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ---- Structured logging setup (structlog) ----
def configure_logging():
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            timestamper,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, LOG_LEVEL.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
    )

configure_logging()
logger = structlog.get_logger()

# ---- Prometheus metrics (optional but included) ----
REQUEST_COUNTER = Counter("store_requests_total", "Total HTTP requests", ["path", "method", "status"])

# ---- FastAPI app ----
app = FastAPI(title="Entity Store Service", version="1.0.0")

# DB client globals
_mongo_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None

# Collection name
COLLECTION_NAME = os.getenv("ENTITY_COLLECTION_NAME", "entity")

# Utility: convert ObjectId-safe
def _to_objectid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {id_str}")

# ---- Database methods adapted from original store.py ----
async def get_collection():
    if not _db:
        raise RuntimeError("database is not initialized")
    return _db.get_collection(COLLECTION_NAME)


async def add_entity(entity_data: dict) -> Entity:
    coll = await get_collection()
    result = await coll.insert_one(entity_data)
    return await get_entity(str(result.inserted_id))


async def get_entity(id: str) -> Entity:
    coll = await get_collection()
    entity = await coll.find_one({"_id": _to_objectid(id)})
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return Entity.model_validate(entity)


async def list_entities() -> List[Entity]:
    coll = await get_collection()
    cursor = coll.find()
    entities = await cursor.to_list(length=None)
    return [Entity.model_validate(entity) for entity in entities]


async def edit_entity(entity_id: str, entity_data: dict):
    coll = await get_collection()
    res = await coll.update_one({"_id": _to_objectid(entity_id)}, {"$set": entity_data})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Entity not found")


async def delete_entity(entity_id: str):
    coll = await get_collection()
    res = await coll.delete_one({"_id": _to_objectid(entity_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entity not found")


async def list_synonyms() -> Dict[str, str]:
    """list all synonyms across the entities"""
    synonyms = {}

    entities = await list_entities()
    for entity in entities:
        # Expecting entity.entity_values to be a list of objects/dicts with 'synonyms' and 'value'
        for value in getattr(entity, "entity_values", []) or []:
            # value could be pydantic model or dict
            synonyms_list = value.get("synonyms") if isinstance(value, dict) else getattr(value, "synonyms", None)
            value_text = value.get("value") if isinstance(value, dict) else getattr(value, "value", None)
            if synonyms_list:
                for synonym in synonyms_list:
                    synonyms[synonym] = value_text
    return synonyms


async def bulk_import_entities(entities: List[Dict]) -> List[str]:
    created_entities = []
    if entities:
        coll = await get_collection()
        for entity in entities:
            result = await coll.update_one(
                {"name": entity.get("name")}, {"$set": entity}, upsert=True
            )
            if result.upserted_id:
                created_entities.append(str(result.upserted_id))
    return created_entities


# ---- FastAPI Routes that expose the store operations ----
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        REQUEST_COUNTER.labels(path=request.url.path, method=request.method, status=response.status_code).inc()
        return response
    except Exception as exc:
        # Log error and increment metric for 500
        logger.error("unhandled_exception", exc_info=exc, path=request.url.path, method=request.method)
        REQUEST_COUNTER.labels(path=request.url.path, method=request.method, status=500).inc()
        raise


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/readiness")
async def readiness():
    # simple DB ping
    try:
        if not _mongo_client:
            raise RuntimeError("mongo client not initialized")
        await _mongo_client.admin.command("ping")
        return {"status": "ready"}
    except Exception as e:
        logger.warning("readiness_failed", error=str(e))
        raise HTTPException(status_code=503, detail="not ready")


@app.get("/metrics")
async def metrics():
    # expose prometheus metrics
    data = generate_latest()
    return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.post("/entities", status_code=status.HTTP_201_CREATED)
async def create_entity(payload: Dict):
    created = await add_entity(payload)
    return JSONResponse(status_code=201, content=created.model_dump() if hasattr(created, 'model_dump') else created.dict())


@app.get("/entities", response_model=List[Dict])
async def get_entities():
    entities = await list_entities()
    # Convert pydantic models to dicts
    out = []
    for e in entities:
        if hasattr(e, "model_dump"):
            out.append(e.model_dump())
        else:
            out.append(e.dict())
    return out


@app.get("/entities/{entity_id}")
async def get_entity_route(entity_id: str):
    entity = await get_entity(entity_id)
    if hasattr(entity, "model_dump"):
        return entity.model_dump()
    return entity.dict()


@app.put("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_entity_route(entity_id: str, payload: Dict):
    await edit_entity(entity_id, payload)
    return JSONResponse(status_code=204, content=None)


@app.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity_route(entity_id: str):
    await delete_entity(entity_id)
    return JSONResponse(status_code=204, content=None)


@app.get("/synonyms")
async def get_synonyms():
    synonyms = await list_synonyms()
    return synonyms


@app.post("/entities/bulk_import")
async def bulk_import_route(payload: List[Dict]):
    created = await bulk_import_entities(payload)
    return {"created": created}


# ---- Application startup / shutdown and graceful termination ----
async def init_db():
    global _mongo_client, _db
    if _mongo_client:
        return
    logger.info("initializing_mongo", uri=MONGODB_URI, db=MONGODB_DB, maxPoolSize=MAX_POOL_SIZE)
    _mongo_client = AsyncIOMotorClient(MONGODB_URI, maxPoolSize=MAX_POOL_SIZE)
    _db = _mongo_client[MONGODB_DB]


async def close_db():
    global _mongo_client
    if _mongo_client:
        logger.info("closing_mongo")
        _mongo_client.close()
        _mongo_client = None


@app.on_event("startup")
async def on_startup():
    await init_db()
    logger.info("app_startup")


@app.on_event("shutdown")
async def on_shutdown():
    await close_db()
    logger.info("app_shutdown")


# Graceful SIGTERM handling for deployments that send SIGTERM (Kubernetes, ECS)
def _install_signal_handlers(loop):
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_shutdown(s)))
    except NotImplementedError:
        # Windows or event loop that doesn't support signals
        pass


async def _shutdown(sig):
    logger.info("received_shutdown_signal", signal=str(sig))
    await close_db()
    # allow the ASGI server to stop. If uvicorn was started from __main__, it will handle exit.


# If this module is run directly, start uvicorn
if __name__ == "__main__":
    import uvicorn

    loop = asyncio.get_event_loop()
    _install_signal_handlers(loop)
    logger.info("starting_uvicorn", host=SERVICE_HOST, port=SERVICE_PORT)
    uvicorn.run("store:app", host=SERVICE_HOST, port=SERVICE_PORT, log_level=LOG_LEVEL.lower(), loop="asyncio")
