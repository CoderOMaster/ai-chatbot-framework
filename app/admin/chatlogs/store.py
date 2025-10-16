import os
import sys
import asyncio
import signal
import logging
from logging.config import dictConfig
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import motor.motor_asyncio
from pymongo import ASCENDING, DESCENDING

# Prometheus
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response

# Structured logging
from pythonjsonlogger import jsonlogger

# Internal schemas (keep using the same models as original project)
# Adjust import path if your project structure differs
try:
    from app.admin.chatlogs.schemas import (
        ChatLog,
        ChatLogResponse,
        ChatThreadInfo,
    )
except Exception:
    # Fallback definitions if internal schema module is not importable during standalone dev.
    # These fallback classes help local testing; in production the real models should exist.
    class ChatLog(BaseModel):
        user_message: str
        bot_message: str
        date: datetime
        context: dict = {}

    class ChatThreadInfo(BaseModel):
        thread_id: str
        date: datetime

    class ChatLogResponse(BaseModel):
        total: int
        page: int
        limit: int
        conversations: List[ChatThreadInfo]

# Environment variables with sensible defaults
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "chatbot")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "state")
MONGODB_MAX_POOL_SIZE = int(os.getenv("MONGODB_MAX_POOL_SIZE", "50"))
MONGODB_MIN_POOL_SIZE = int(os.getenv("MONGODB_MIN_POOL_SIZE", "0"))
SERVICE_HOST = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Configure structured JSON logging
logger = logging.getLogger("chatlog_service")
logger.setLevel(LOG_LEVEL)
logHandler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "chatlog_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram("chatlog_request_latency_seconds", "Request latency", ["endpoint"]) 

app = FastAPI(title="ChatLog Microservice")

# CORS - adjust origins as needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global DB references will be set on startup
mongo_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
collection = None
shutdown_event = asyncio.Event()


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = asyncio.get_event_loop().time()
    try:
        response = await call_next(request)
    except Exception as e:
        # Count exceptions as 500
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=500).inc()
        logger.exception("Unhandled error in request", extra={"path": request.url.path})
        raise
    finally:
        elapsed = asyncio.get_event_loop().time() - start
        REQUEST_LATENCY.labels(endpoint=request.url.path).observe(elapsed)
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=response.status_code).inc()
    return response


@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    """Simple liveness check"""
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/readiness")
async def readiness():
    """Check DB connectivity for readiness"""
    global mongo_client
    if not mongo_client:
        logger.warning("readiness check: no mongo client initialized")
        raise HTTPException(status_code=503, detail="no db client")
    try:
        # ping the primary
        await mongo_client.admin.command("ping")
        return JSONResponse(status_code=200, content={"status": "ready"})
    except Exception as e:
        logger.exception("readiness check failed")
        raise HTTPException(status_code=503, detail="db ping failed")


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        # Accept ISO format
        return datetime.fromisoformat(date_str)
    except Exception:
        # fallback: try common formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except Exception:
                continue
    raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str}")


@app.get("/chatlogs", response_model=ChatLogResponse)
async def list_chatlogs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """List chat threads (paginated). Keeps original aggregation logic."""
    global collection
    if collection is None:
        logger.error("collection not initialized")
        raise HTTPException(status_code=503, detail="db not ready")

    skip = (page - 1) * limit

    s_date = _parse_date(start_date)
    e_date = _parse_date(end_date)

    query = {}
    if s_date or e_date:
        query["date"] = {}
        if s_date:
            query["date"]["$gte"] = s_date
        if e_date:
            query["date"]["$lte"] = e_date

    # total unique thread count
    pipeline_count = [
        {"$match": query},
        {"$group": {"_id": "$thread_id"}},
        {"$count": "total"},
    ]
    try:
        result = await collection.aggregate(pipeline_count).to_list(1)
        total = result[0]["total"] if result else 0

        pipeline = [
            {"$match": query},
            {"$sort": {"date": -1}},
            {
                "$group": {
                    "_id": "$thread_id",
                    "thread_id": {"$first": "$thread_id"},
                    "date": {"$first": "$date"},
                }
            },
            {"$sort": {"date": -1}},
            {"$skip": skip},
            {"$limit": limit},
        ]

        conversations = []
        async for doc in collection.aggregate(pipeline):
            conversations.append(
                ChatThreadInfo(thread_id=doc["thread_id"], date=doc["date"])
            )

        response = ChatLogResponse(total=total, page=page, limit=limit, conversations=conversations)
        logger.info("list_chatlogs", extra={"page": page, "limit": limit, "total": total})
        return response
    except Exception:
        logger.exception("Error listing chatlogs")
        raise HTTPException(status_code=500, detail="internal error")


@app.get("/chatlogs/{thread_id}", response_model=List[ChatLog])
async def get_chat_thread(thread_id: str):
    """Get complete conversation history for a specific thread"""
    global collection
    if collection is None:
        logger.error("collection not initialized")
        raise HTTPException(status_code=503, detail="db not ready")

    try:
        cursor = collection.find({"thread_id": thread_id}).sort("date", 1)
        messages = await cursor.to_list(length=None)

        if not messages:
            raise HTTPException(status_code=404, detail="thread not found")

        chat_logs: List[ChatLog] = []
        for msg in messages:
            chat_logs.append(
                ChatLog(
                    user_message=msg.get("user_message"),
                    bot_message=msg.get("bot_message"),
                    date=msg.get("date"),
                    context=msg.get("context", {}),
                )
            )

        return chat_logs
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching chat thread %s", thread_id)
        raise HTTPException(status_code=500, detail="internal error")


async def _init_db():
    """Initialize MongoDB connection with pooling."""
    global mongo_client, collection
    if mongo_client:
        return
    logger.info("Initializing MongoDB client", extra={"uri": MONGODB_URI})
    mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
        MONGODB_URI,
        maxPoolSize=MONGODB_MAX_POOL_SIZE,
        minPoolSize=MONGODB_MIN_POOL_SIZE,
        serverSelectionTimeoutMS=5000,
    )
    # Optionally set the app-wide client if other internal modules import app.database.client
    try:
        # Try to set a module variable if it exists in the package
        import app.database as _db_mod

        setattr(_db_mod, "client", mongo_client)
        logger.info("Updated app.database.client for compatibility")
    except Exception:
        # Not fatal
        pass

    db = mongo_client[MONGODB_DB]
    collection = db[MONGODB_COLLECTION]


async def _close_db():
    global mongo_client
    if mongo_client:
        logger.info("Closing MongoDB client")
        mongo_client.close()
        mongo_client = None


@app.on_event("startup")
async def startup_event():
    await _init_db()
    # Hook SIGTERM to trigger graceful shutdown
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("Received termination signal, initiating shutdown")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows or event loop that doesn't support signal handlers
            pass


@app.on_event("shutdown")
async def shutdown_event_handler():
    await _close_db()


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting ChatLog service", extra={"host": SERVICE_HOST, "port": SERVICE_PORT})
    uvicorn.run("__main__:app", host=SERVICE_HOST, port=SERVICE_PORT, log_config=None)
