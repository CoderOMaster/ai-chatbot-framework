### File: app/__init__.py
# Package marker (empty)

### File: app/database.py
from typing import Optional
import os
import logging
from pymongo import MongoClient
from bson import ObjectId

# Simple alias for ObjectIdField to keep compatibility with existing schemas
# This is intentionally a simple alias (str) so Pydantic validation remains straightforward.
# If you have a richer ObjectId type in your environment, replace this with that implementation.
ObjectIdField = str

logger = logging.getLogger(__name__)

DEFAULT_MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DEFAULT_DB_NAME = os.getenv("MONGO_DB", "mydb")

_mongo_client: Optional[MongoClient] = None


def create_mongo_client(uri: Optional[str] = None, max_pool_size: int = 50) -> MongoClient:
    """Create a MongoClient with connection pooling.

    This function ensures a single client is created per process and configured
    with a reasonable pool size for microservices.
    """
    global _mongo_client
    if _mongo_client is None:
        uri = uri or DEFAULT_MONGO_URI
        logger.info("Creating MongoClient", extra={"mongo_uri": uri, "maxPoolSize": max_pool_size})
        # serverSelectionTimeoutMS to fail fast if DB unreachable
        _mongo_client = MongoClient(uri, maxPoolSize=int(max_pool_size), serverSelectionTimeoutMS=5000)
    return _mongo_client


def get_db(client: MongoClient, db_name: Optional[str] = None):
    db_name = db_name or DEFAULT_DB_NAME
    return client[db_name]


def close_mongo_client():
    """Close the global MongoClient if present."""
    global _mongo_client
    if _mongo_client is not None:
        try:
            _mongo_client.close()
        except Exception:
            logger.exception("Error closing MongoClient")
        _mongo_client = None


def generate_object_id() -> str:
    return str(ObjectId())


### File: app/schemas.py
from app.database import ObjectIdField, generate_object_id
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any


class LabeledSentences(BaseModel):
    """Schema for labeled sentences"""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    data: List[str] = []

    # pydantic v2 config helper
    model_config = ConfigDict(arbitrary_types_allowed=True)


class Parameter(BaseModel):
    """Parameter schema for intent parameters"""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ApiDetails(BaseModel):
    """API details schema for intent API triggers"""

    url: str
    requestType: str
    headers: List[Dict[str, str]] = []
    isJson: bool = False
    jsonData: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        headers = {}
        for header in self.headers:
            # support both keys used previously: headerKey/headerValue
            key = header.get("headerKey") or header.get("key")
            value = header.get("headerValue") or header.get("value")
            if key:
                headers[key] = value or ""
        return headers


class Intent(BaseModel):
    """Base schema for intent"""

    # support validation alias for MongoDB _id field
    id: Optional[ObjectIdField] = Field(default=None, alias="_id")
    name: str
    userDefined: bool = True
    intentId: str
    apiTrigger: bool = False
    apiDetails: Optional[ApiDetails] = None
    speechResponse: str
    parameters: List[Parameter] = []
    labeledSentences: List[LabeledSentences] = []
    trainingData: List[Dict[str, Any]] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


### File: app/logging_config.py
import logging
import os
from pythonjsonlogger import jsonlogger


def configure_logging():
    level_name = os.getenv("LOG_LEVEL", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Remove default handlers
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # JSON formatter
    fmt = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    logger.addHandler(handler)


### File: app/main.py
import os
import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pymongo.errors import PyMongoError

from app.logging_config import configure_logging
from app.database import create_mongo_client, get_db, close_mongo_client
from app.schemas import Intent

# Configure structured logging early
configure_logging()
logger = logging.getLogger("app.main")

# Metrics (optional)
REQUEST_COUNT = Counter("app_requests_total", "Total HTTP Requests", ["method", "endpoint", "http_status"])


# Environment
PORT = int(os.getenv("PORT", "8000"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mydb")
MONGO_MAX_POOL = int(os.getenv("MONGO_MAX_POOL", "50"))
SERVICE_NAME = os.getenv("SERVICE_NAME", "intent-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler: create DB client and handle graceful shutdown."""
    logger.info("Starting application", extra={"service": SERVICE_NAME})
    # create mongo client and attach to app state
    try:
        client = create_mongo_client(MONGO_URI, max_pool_size=MONGO_MAX_POOL)
        app.state.mongo_client = client
        app.state.db = get_db(client, MONGO_DB)
        logger.info("MongoDB client created and connected", extra={"db": MONGO_DB})
    except Exception:
        logger.exception("Failed to create MongoDB client")
        raise

    # Provide a shutdown event to other tasks
    shutdown_event = asyncio.Event()
    app.state.shutdown_event = shutdown_event

    # Setup signal handlers to log when process receives termination signals
    loop = asyncio.get_event_loop()

    def _sigterm_handler(*_):
        logger.info("SIGTERM/SIGINT received, setting shutdown event")
        try:
            shutdown_event.set()
        except Exception:
            logger.exception("Error setting shutdown event")

    # Register handlers (these coexist with uvicorn/gunicorn handlers; purpose here is logging/cleanup)
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _sigterm_handler)
        except NotImplementedError:
            # Some platforms (Windows) may not support add_signal_handler
            pass

    try:
        yield
    finally:
        # Close DB connections
        try:
            close_mongo_client()
            logger.info("MongoDB client closed")
        except Exception:
            logger.exception("Error closing MongoDB client during shutdown")
        logger.info("Application shutdown complete")


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        # Count as server error
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise
    finally:
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=str(status_code)).inc()
    return response


@app.get("/health")
async def health():
    """Liveness probe. Returns 200 if the process is running."""
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok", "service": SERVICE_NAME})


@app.get("/readiness")
async def readiness():
    """Readiness probe. Checks DB connectivity. Returns 200 if DB ping successful, else 503."""
    client = getattr(app.state, "mongo_client", None)
    if not client:
        logger.warning("Readiness check failed: no Mongo client attached")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db-client-not-initialized")
    try:
        # serverSelectionTimeoutMS on client creation ensures ping fails quickly
        client.admin.command("ping")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready"})
    except PyMongoError:
        logger.exception("Readiness check: MongoDB ping failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db-unavailable")


@app.post("/intents", status_code=201)
async def create_intent(intent: Intent):
    """Example endpoint to insert an Intent into MongoDB.

    This demonstrates DB usage and schema validation while keeping the service minimal.
    """
    db = getattr(app.state, "db", None)
    if db is None:
        logger.error("Create intent failed: DB not available")
        raise HTTPException(status_code=503, detail="db-not-available")

    # Convert Intent to dict. Use by_alias=True to write _id field if present.
    payload = intent.model_dump(by_alias=True)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: db.intents.insert_one(payload))
    except Exception:
        logger.exception("Failed to insert intent into DB")
        raise HTTPException(status_code=500, detail="db-insert-failed")

    return JSONResponse(status_code=201, content={"inserted_id": str(res.inserted_id)})


@app.get("/intents/{intent_id}")
async def get_intent(intent_id: str):
    db = getattr(app.state, "db", None)
    if db is None:
        logger.error("Get intent failed: DB not available")
        raise HTTPException(status_code=503, detail="db-not-available")
    try:
        doc = await asyncio.get_event_loop().run_in_executor(None, lambda: db.intents.find_one({"_id": intent_id}) )
        if not doc:
            raise HTTPException(status_code=404, detail="intent-not-found")
        # Return document directly (pymongo returns dicts that are JSON serializable if ObjectIds are stringified by the app)
        # Ensure any ObjectId is stringified
        if isinstance(doc.get("_id"), (bytes,)):
            doc["_id"] = str(doc["_id"])
        return JSONResponse(status_code=200, content=doc)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch intent from DB")
        raise HTTPException(status_code=500, detail="db-query-failed")


@app.get("/metrics")
async def metrics():
    # Expose Prometheus metrics
    data = generate_latest()
    return PlainTextResponse(content=data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    # When running locally for development
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, log_config=None, access_log=False, workers=1)
