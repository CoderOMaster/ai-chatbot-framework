from __future__ import annotations

import os
import sys
import signal
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException, status, Request, Response, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Attempt to import project Intent model, otherwise provide a fallback pydantic model.
try:
    from app.admin.intents.schemas import Intent as ProjectIntent
    Intent = ProjectIntent
except Exception:  # pragma: no cover - fallback for standalone usage
    class Intent(BaseModel):
        name: str
        description: Optional[str] = None
        samples: Optional[List[str]] = []

        # Provide model_validate compatibility for Pydantic v2 style call used in original code
        @classmethod
        def model_validate(cls, obj: dict) -> "Intent":
            if obj is None:
                raise ValueError("No data to validate")
            data = dict(obj)
            # convert ObjectId to string if present
            if "_id" in data:
                data["id"] = str(data.pop("_id"))
            return cls(**data)

# Environment configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "app_db")
MONGO_MAX_POOL_SIZE = int(os.getenv("MONGO_MAX_POOL_SIZE", "50"))
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SERVICE_NAME = os.getenv("SERVICE_NAME", "intent-service")

# Structured JSON logging configuration
logger = logging.getLogger(SERVICE_NAME)
logger.setLevel(LOG_LEVEL)
handler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Prometheus metrics (basic)
REQUEST_COUNT = Counter(
    "intent_service_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"],
)
REQUEST_LATENCY = Histogram("intent_service_request_latency_seconds", "Request latency in seconds", ["endpoint"])

# FastAPI app
app = FastAPI(title=SERVICE_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database client placeholders
mongo_client: Optional[AsyncIOMotorClient] = None
intent_collection: Optional[AsyncIOMotorCollection] = None

# Helper - metrics and logging middleware
@app.middleware("http")
async def add_metrics_and_logging(request: Request, call_next):
    endpoint = request.url.path
    method = request.method
    with REQUEST_LATENCY.labels(endpoint=endpoint).time():
        try:
            response = await call_next(request)
        except Exception as exc:
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status="500").inc()
            logger.exception("unhandled_exception", extra={"path": endpoint, "method": method})
            raise
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(response.status_code)).inc()
    logger.info(
        "request_complete",
        extra={
            "path": endpoint,
            "method": method,
            "status_code": response.status_code,
            "client": request.client.host if request.client else None,
        },
    )
    return response

# Lifespan: startup & shutdown (handles graceful termination)
@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, intent_collection
    logger.info("startup", extra={"mongo_uri": MONGO_URI, "db": DB_NAME})
    mongo_client = AsyncIOMotorClient(MONGO_URI, maxPoolSize=MONGO_MAX_POOL_SIZE)
    db = mongo_client[DB_NAME]
    intent_collection = db.get_collection("intent")

    # install signal handlers for graceful shutdown in addition to uvicorn's
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler(*_):
        logger.info("received_termination_signal", extra={"signal": True})
        loop.create_task(_shutdown())

    async def _shutdown():
        if not stop_event.is_set():
            stop_event.set()
            logger.info("shutting_down", extra={"closing_mongo": True})
            try:
                mongo_client.close()
            except Exception:
                logger.exception("error_closing_mongo")
            # allow tasks to finish briefly
            await asyncio.sleep(0.1)
            # stop the loop only when run externally — uvicorn will stop the process

    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(s, _signal_handler)
        except NotImplementedError:
            # Windows or environments where loop signal handlers are not implemented
            pass

    try:
        yield
    finally:
        # final cleanup
        if mongo_client:
            mongo_client.close()
        logger.info("stopped")

app.router.lifespan_context = lifespan

# Dependency to ensure collection is available
async def get_collection() -> AsyncIOMotorCollection:
    if intent_collection is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return intent_collection

# Utility functions mirroring original store.py but now using dependency injection
async def add_intent_to_db(collection: AsyncIOMotorCollection, intent_data: dict) -> Intent:
    result = await collection.insert_one(intent_data)
    return await get_intent_from_db(collection, str(result.inserted_id))

async def get_intent_from_db(collection: AsyncIOMotorCollection, id: str) -> Intent:
    try:
        oid = ObjectId(id)
    except Exception:
        logger.warning("invalid_object_id", extra={"id": id})
        raise HTTPException(status_code=400, detail="Invalid id format")
    intent = await collection.find_one({"_id": oid})
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    # original code used Intent.model_validate
    return Intent.model_validate(intent)

async def list_intents_from_db(collection: AsyncIOMotorCollection) -> List[Intent]:
    cursor = collection.find()
    intents = []
    async for doc in cursor:
        intents.append(Intent.model_validate(doc))
    return intents

async def edit_intent_in_db(collection: AsyncIOMotorCollection, intent_id: str, intent_data: dict):
    try:
        oid = ObjectId(intent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")
    result = await collection.update_one({"_id": oid}, {"$set": intent_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Intent not found")

async def delete_intent_in_db(collection: AsyncIOMotorCollection, intent_id: str):
    try:
        oid = ObjectId(intent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")
    result = await collection.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Intent not found")

async def bulk_import_intents_to_db(collection: AsyncIOMotorCollection, intents: List[Dict]) -> List[str]:
    created_intents: List[str] = []
    if intents:
        for intent in intents:
            result = await collection.update_one(
                {"name": intent.get("name")}, {"$set": intent}, upsert=True
            )
            if getattr(result, "upserted_id", None):
                created_intents.append(str(result.upserted_id))
    return created_intents

# API endpoints
@app.get("/health", summary="Liveness probe")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})

@app.get("/readiness", summary="Readiness probe")
async def readiness(collection: AsyncIOMotorCollection = Depends(get_collection)) -> JSONResponse:
    # Try a cheap DB operation
    try:
        # ping returns {'ok': 1.0} on success
        await collection.database.client.admin.command("ping")
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        logger.exception("readiness_failure")
        raise HTTPException(status_code=503, detail="database not ready")

@app.get("/metrics", summary="Prometheus metrics")
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@app.post("/intents", status_code=status.HTTP_201_CREATED)
async def create_intent(payload: dict, collection: AsyncIOMotorCollection = Depends(get_collection)) -> JSONResponse:
    intent = await add_intent_to_db(collection, payload)
    return JSONResponse(content=intent.model_dump(), status_code=status.HTTP_201_CREATED)

@app.get("/intents", response_model=List[Intent])
async def list_intents(collection: AsyncIOMotorCollection = Depends(get_collection)) -> List[Intent]:
    return await list_intents_from_db(collection)

@app.get("/intents/{intent_id}")
async def get_intent(intent_id: str, collection: AsyncIOMotorCollection = Depends(get_collection)) -> Intent:
    return await get_intent_from_db(collection, intent_id)

@app.put("/intents/{intent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_intent(intent_id: str, payload: dict, collection: AsyncIOMotorCollection = Depends(get_collection)):
    await edit_intent_in_db(collection, intent_id, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.delete("/intents/{intent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_intent(intent_id: str, collection: AsyncIOMotorCollection = Depends(get_collection)):
    await delete_intent_in_db(collection, intent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.post("/intents/_bulk_import", summary="Bulk import or upsert intents")
async def bulk_import(intents: List[Dict], collection: AsyncIOMotorCollection = Depends(get_collection)) -> JSONResponse:
    created = await bulk_import_intents_to_db(collection, intents)
    return JSONResponse({"created_ids": created})

# Root
@app.get("/")
async def root():
    return {"service": SERVICE_NAME, "status": "running"}

# If being run directly (for local dev)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("__main__:app", host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower(), loop="asyncio")
