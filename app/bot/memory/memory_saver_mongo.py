from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import asyncio
import logging
import signal
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorClient
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry
from pythonjsonlogger import jsonlogger

# Internal imports (kept as in original project)
from app.bot.memory.models import State
from app.bot.memory import MemorySaver

# Environment-configurable settings with sensible defaults
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "chatbot")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "state")
MAX_POOL_SIZE = int(os.getenv("MONGO_MAX_POOL_SIZE", "100"))
MIN_POOL_SIZE = int(os.getenv("MONGO_MIN_POOL_SIZE", "0"))
SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

# Setup structured JSON logging
logger = logging.getLogger("memory_saver_service")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
log_handler.setFormatter(formatter)
logger.handlers = [log_handler]

# Prometheus metrics
REQUEST_COUNT = Counter(
    "api_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "http_status"],
)
REQUEST_LATENCY = Histogram("api_request_duration_seconds", "Request latency (seconds)", ["endpoint"])

app = FastAPI(title="memory-saver-mongo", version="1.0.0")

# Allow CORS for debugging / internal communication (tweak in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class MemorySaverMongo(MemorySaver):
    """
    MemorySaverMongo implements the MemorySaver interface for MongoDB.
    Connection options use environment variables for pooling and timeouts.
    """

    def __init__(self, client: AsyncIOMotorClient, db_name: str, collection_name: str):
        self.client = client
        self.db = client.get_database(db_name)
        self.collection = self.db.get_collection(collection_name)

    async def save(self, thread_id: str, state: State):
        # Keep original behavior: insert a full state dict
        await self.collection.insert_one(state.to_dict())

    async def get(self, thread_id: str) -> Optional[State]:
        result = await self.collection.find_one(
            {"thread_id": thread_id},
            {"_id": 0, "nlu": 0, "date": 0, "user_message": 0, "bot_message": 0},
            sort=[("$natural", -1)],
        )
        if result:
            return State.from_dict(result)
        return None

    async def get_all(self, thread_id: str) -> List[State]:
        results = await self.collection.find({"thread_id": thread_id}, sort=[("$natural", -1)]).to_list(length=None)
        return [State.from_dict(result) for result in results]


# Global app state to hold the client and saver
class AppState:
    client: Optional[AsyncIOMotorClient] = None
    saver: Optional[MemorySaverMongo] = None

app_state = AppState()


@app.on_event("startup")
async def startup_event():
    # Build Mongo client with pooling options
    logger.info("Starting up: creating MongoDB client", extra={"mongodb_uri": MONGODB_URI})
    # Motor uses pymongo-style kwargs
    client = AsyncIOMotorClient(
        MONGODB_URI,
        maxPoolSize=MAX_POOL_SIZE,
        minPoolSize=MIN_POOL_SIZE,
        serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
    )

    # Quick async ping to ensure connectivity (non-blocking)
    try:
        await client.admin.command("ping")
        logger.info("MongoDB ping succeeded")
    except Exception as e:
        # Log the error — readiness probe will catch this later
        logger.error("MongoDB ping failed during startup", exc_info=True)

    app_state.client = client
    app_state.saver = MemorySaverMongo(client=client, db_name=DB_NAME, collection_name=COLLECTION_NAME)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutdown initiated: closing MongoDB client")
    try:
        if app_state.client is not None:
            # Motor client close is synchronous (closes background I/O threads)
            app_state.client.close()
            logger.info("MongoDB client closed")
    except Exception:
        logger.exception("Error while closing MongoDB client")


# Graceful SIGTERM handling for environments that don't run uvicorn's signal handling
def _handle_sigterm(*_):
    logger.info("SIGTERM received: requesting shutdown")
    # If running under uvicorn, uvicorn handles signals. We attempt to stop event loop tasks as a best-effort.
    loop = asyncio.get_event_loop()
    for task in asyncio.all_tasks(loop):
        if task is not asyncio.current_task(loop):
            task.cancel()


signal.signal(signal.SIGTERM, _handle_sigterm)


# Middleware to collect performance metrics and JSON-structured access logs
@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    endpoint = request.url.path
    method = request.method
    with REQUEST_LATENCY.labels(endpoint=endpoint).time():
        try:
            response = await call_next(request)
        except Exception as exc:
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(500)).inc()
            logger.exception("Unhandled exception in request", extra={"method": method, "endpoint": endpoint})
            raise

    REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(response.status_code)).inc()
    # Structured request log
    logger.info("request_finished", extra={
        "method": method,
        "endpoint": endpoint,
        "status_code": response.status_code,
        "client_host": request.client.host if request.client else None,
    })
    return response


@app.get("/health", response_class=JSONResponse)
async def health():
    # Lightweight health check
    return {"status": "ok"}


@app.get("/readiness", response_class=JSONResponse)
async def readiness():
    # Check DB is reachable
    client = app_state.client
    if client is None:
        logger.warning("readiness: no mongo client available")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db_unavailable")
    try:
        # ping with a short timeout (serverSelectionTimeoutMS controls this already)
        await client.admin.command("ping")
        return {"status": "ready"}
    except Exception:
        logger.exception("readiness: mongo ping failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db_unavailable")


@app.post("/state/{thread_id}")
async def save_state(thread_id: str, request: Request):
    """
    Save a state record. Expects a JSON body compatible with your app.bot.memory.models.State.
    The original saver inserted the whole State dict; we preserve that behavior.
    """
    if app_state.saver is None:
        logger.error("save_state called but saver is not initialized")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="service_unavailable")

    payload = await request.json()
    try:
        # Convert incoming payload to domain State object
        state_obj = State.from_dict(payload)
    except Exception:
        # If State.from_dict is strict and fails, we surface a 400
        logger.exception("Failed to parse State from request payload")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_state_payload")

    try:
        await app_state.saver.save(thread_id, state_obj)
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={"result": "saved"})
    except Exception:
        logger.exception("Failed to save state to MongoDB")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="save_failed")


@app.get("/state/{thread_id}")
async def get_state(thread_id: str):
    if app_state.saver is None:
        logger.error("get_state called but saver is not initialized")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="service_unavailable")
    try:
        state = await app_state.saver.get(thread_id)
        if state is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        # Return dict representation to be JSON serializable
        return JSONResponse(status_code=status.HTTP_200_OK, content=state.to_dict())
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to read state from MongoDB")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="read_failed")


@app.get("/state/{thread_id}/all")
async def get_all_states(thread_id: str):
    if app_state.saver is None:
        logger.error("get_all_states called but saver is not initialized")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="service_unavailable")
    try:
        states = await app_state.saver.get_all(thread_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=[s.to_dict() for s in states])
    except Exception:
        logger.exception("Failed to read all states from MongoDB")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="read_all_failed")


@app.get("/metrics")
async def metrics():
    # Expose prometheus metrics
    try:
        registry = CollectorRegistry()
        # The default registry contains our metrics already. Instead, use generate_latest(None) which uses the default registry.
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
    except Exception:
        logger.exception("Failed to generate metrics")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="metrics_error")


# Root route for basic info
@app.get("/", response_class=PlainTextResponse)
async def root():
    return "memory-saver-mongo service\n"


if __name__ == "__main__":
    # Only used for local debugging. In production, run with uvicorn/gunicorn.
    import uvicorn

    uvicorn.run("memory_saver_mongo:app", host=APP_HOST, port=APP_PORT, log_level=os.getenv("LOG_LEVEL", "info"))
