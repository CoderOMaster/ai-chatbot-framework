from typing import Optional, Dict, List, Any, Text
import os
import json
import signal
import logging
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

# External/internal dependencies (kept as in original project)
from app.bot.dialogue_manager.models import UserMessage  # internal package dependency

# DB (SQLAlchemy) for persistence with connection pooling
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Text,
    DateTime,
    select,
)

# Prometheus metrics
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# Configuration via environment variables
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_URL = os.getenv("DB_URL", "sqlite:///./states.db")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("1", "true", "yes")
READINESS_TIMEOUT = int(os.getenv("READINESS_TIMEOUT", "3"))

# Structured JSON logging setup
class JSONLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        # include any extra keys that might have been set
        for key, value in record.__dict__.items():
            if key in ("msg", "args", "levelname", "levelno", "name", "exc_info", "exc_text", "stack_info", "lineno", "pathname", "filename", "module", "process", "processName", "thread", "threadName"):
                continue
            if not key.startswith("_"):
                try:
                    json.dumps(value)
                    log_record[key] = value
                except Exception:
                    log_record[key] = str(value)
        return json.dumps(log_record)

logger = logging.getLogger("state-service")
handler = logging.StreamHandler()
handler.setFormatter(JSONLogFormatter())
logger.addHandler(handler)
logger.setLevel(LOG_LEVEL)

# Prometheus metrics
REQUEST_COUNT = Counter("state_service_requests_total", "Total HTTP requests to state service", ["method", "endpoint", "http_status"]) if METRICS_ENABLED else None
STATE_UPSERT_COUNT = Counter("state_upserts_total", "Number of state upserts") if METRICS_ENABLED else None
STATE_GET_COUNT = Counter("state_gets_total", "Number of state gets") if METRICS_ENABLED else None

# SQLAlchemy engine with connection pooling
engine = create_engine(
    DB_URL,
    pool_size=DB_POOL_SIZE,
    max_overflow=10,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite:") else {},
)
metadata = MetaData()
states_table = Table(
    "states",
    metadata,
    Column("thread_id", String, primary_key=True),
    Column("state_json", Text, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

# create table if not exists (synchronous; OK on startup)
metadata.create_all(engine)

# The original State class refactored to live in the microservice while preserving logic
class State:
    def __init__(
        self,
        thread_id: Text,
        user_message: UserMessage = None,
        bot_message: Optional[List[Dict]] = None,
        context: Optional[Dict] = None,
        intent: Optional[Dict] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        extracted_parameters: Optional[Dict] = None,
        missing_parameters: Optional[List[str]] = None,
        complete: bool = False,
        current_node: Text = "",
        date: Optional[datetime] = None,
    ):
        self.thread_id = thread_id
        self.user_message = user_message
        self.bot_message = bot_message
        self.nlu = {}
        self.context = context or {}
        self.intent = intent or {}
        self.parameters = parameters or []
        self.extracted_parameters = extracted_parameters or {}
        self.missing_parameters = missing_parameters or []
        self.complete = complete
        self.current_node = current_node
        self.date = date or datetime.now(timezone.utc)

    def to_dict(self) -> Dict:
        # Guard user_message serialization if None
        user_msg = None
        try:
            user_msg = self.user_message.to_dict() if self.user_message is not None else None
        except Exception:
            # if serialization fails, fall back to repr
            user_msg = repr(self.user_message)

        return {
            "thread_id": self.thread_id,
            "user_message": user_msg,
            "bot_message": self.bot_message,
            "nlu": self.nlu,
            "context": self.context,
            "intent": self.intent,
            "parameters": self.parameters,
            "extracted_parameters": self.extracted_parameters,
            "missing_parameters": self.missing_parameters,
            "complete": self.complete,
            "current_node": self.current_node,
            "date": self.date.isoformat(),
        }

    @classmethod
    def from_dict(cls, state_dict: Dict) -> "State":
        # parse all the fields - keep consistent with original signature
        # user_message is optional; if present, we do not attempt to rehydrate into UserMessage class here
        user_message_obj = None
        if state_dict.get("user_message"):
            # Best-effort: if a dict is passed, attempt to create a UserMessage via constructor
            try:
                # Assume UserMessage has a constructor that accepts **kwargs or a from_dict
                if hasattr(UserMessage, "from_dict"):
                    user_message_obj = UserMessage.from_dict(state_dict["user_message"])
                else:
                    user_message_obj = UserMessage(**state_dict["user_message"])  # type: ignore
            except Exception:
                user_message_obj = None

        date_val = None
        if state_dict.get("date"):
            try:
                date_val = datetime.fromisoformat(state_dict["date"])  # may raise
            except Exception:
                date_val = None

        return cls(
            thread_id=state_dict["thread_id"],
            user_message=user_message_obj,
            bot_message=state_dict.get("bot_message"),
            context=state_dict.get("context"),
            intent=state_dict.get("intent"),
            parameters=state_dict.get("parameters"),
            extracted_parameters=state_dict.get("extracted_parameters"),
            missing_parameters=state_dict.get("missing_parameters"),
            complete=state_dict.get("complete", False),
            current_node=state_dict.get("current_node", ""),
            date=date_val,
        )

    def update(self, user_message: UserMessage):
        self.user_message = user_message
        self.date = datetime.now(timezone.utc)
        try:
            # assume user_message has a context attribute
            if hasattr(user_message, "context") and isinstance(user_message.context, dict):
                self.context.update(user_message.context)
        except Exception:
            logger.debug("Could not merge user_message.context into state.context")

        if self.complete:
            self.bot_message = []
            self.intent = None
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = None

    def get_active_intent_id(self):
        if self.intent:
            return self.intent.get("id")
        return None


# Pydantic models for API (keep simple and permissive)
class RawUserMessage(BaseModel):
    # Accept arbitrary content - keep flexible so client can pass whatever UserMessage.to_dict() would produce
    __root__: Dict[str, Any]

class StatePayload(BaseModel):
    thread_id: str
    user_message: Optional[Dict[str, Any]] = None
    bot_message: Optional[List[Dict]] = None
    context: Optional[Dict] = None
    intent: Optional[Dict] = None
    parameters: Optional[List[Dict[str, Any]]] = None
    extracted_parameters: Optional[Dict] = None
    missing_parameters: Optional[List[str]] = None
    complete: Optional[bool] = False
    current_node: Optional[str] = ""
    date: Optional[str] = None


# FastAPI app
app = FastAPI(title="state-service", version="1.0.0")

# Helper functions for DB operations
def upsert_state_to_db(state: State) -> None:
    j = state.to_dict()
    thread_id = state.thread_id
    updated_at = state.date
    state_json = json.dumps(j)
    with engine.begin() as conn:
        # Try update then insert fallback
        stmt = select(states_table.c.thread_id).where(states_table.c.thread_id == thread_id)
        res = conn.execute(stmt).fetchone()
        if res:
            conn.execute(
                states_table.update().where(states_table.c.thread_id == thread_id).values(state_json=state_json, updated_at=updated_at)
            )
        else:
            conn.execute(
                states_table.insert().values(thread_id=thread_id, state_json=state_json, updated_at=updated_at)
            )


def get_state_from_db(thread_id: str) -> Optional[Dict]:
    with engine.connect() as conn:
        stmt = select([states_table.c.state_json, states_table.c.updated_at]).where(states_table.c.thread_id == thread_id)
        res = conn.execute(stmt).fetchone()
        if not res:
            return None
        state_json, updated_at = res
        try:
            parsed = json.loads(state_json)
            return parsed
        except Exception:
            return {"thread_id": thread_id, "state_json": state_json, "updated_at": updated_at.isoformat() if updated_at else None}


# Middleware-like helper to increment metrics
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    response = None
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        return response
    finally:
        if METRICS_ENABLED and REQUEST_COUNT is not None:
            try:
                REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=status_code if response is not None else "500").inc()
            except Exception:
                pass


# Health endpoint
@app.get("/health")
async def health():
    logger.info("Health check requested")
    return JSONResponse({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"})


# Readiness endpoint - checks DB connectivity
@app.get("/readiness")
async def readiness():
    logger.info("Readiness probe requested")
    # Try a lightweight DB operation
    try:
        with engine.connect() as conn:
            conn.execute(select([1])).fetchone()
        return JSONResponse({"ready": True})
    except Exception as e:
        logger.warning("Readiness failed: %s", str(e))
        raise HTTPException(status_code=503, detail="DB connection not ready")


# Expose Prometheus metrics if enabled
@app.get("/metrics")
async def metrics():
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics not enabled")
    data = generate_latest()
    return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


# POST /state - create or update a state
@app.post("/state")
async def create_or_update_state(payload: StatePayload):
    # Construct State object
    try:
        user_msg_obj = None
        if payload.user_message is not None:
            # Try to create a UserMessage instance if possible, otherwise keep raw dict
            try:
                if hasattr(UserMessage, "from_dict"):
                    user_msg_obj = UserMessage.from_dict(payload.user_message)
                else:
                    user_msg_obj = UserMessage(**payload.user_message)  # type: ignore
            except Exception:
                user_msg_obj = None

        date_val = None
        if payload.date:
            try:
                date_val = datetime.fromisoformat(payload.date)
            except Exception:
                date_val = None

        state = State(
            thread_id=payload.thread_id,
            user_message=user_msg_obj,
            bot_message=payload.bot_message,
            context=payload.context,
            intent=payload.intent,
            parameters=payload.parameters,
            extracted_parameters=payload.extracted_parameters,
            missing_parameters=payload.missing_parameters,
            complete=payload.complete or False,
            current_node=payload.current_node or "",
            date=date_val,
        )

        # Persist to DB (synchronous operation)
        upsert_state_to_db(state)

        if METRICS_ENABLED and STATE_UPSERT_COUNT is not None:
            try:
                STATE_UPSERT_COUNT.inc()
            except Exception:
                pass

        logger.info("Upserted state", extra={"thread_id": payload.thread_id})
        return JSONResponse({"status": "ok", "thread_id": payload.thread_id})
    except Exception as e:
        logger.exception("Failed to upsert state: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# GET /state/{thread_id} - retrieve state
@app.get("/state/{thread_id}")
async def get_state(thread_id: str):
    try:
        raw = get_state_from_db(thread_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="state not found")

        if METRICS_ENABLED and STATE_GET_COUNT is not None:
            try:
                STATE_GET_COUNT.inc()
            except Exception:
                pass

        logger.info("Fetched state", extra={"thread_id": thread_id})
        return JSONResponse(raw)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch state: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# Graceful shutdown handling
shutdown_event = asyncio.Event()

def _handle_termination(signame):
    logger.info("Received signal %s, initiating graceful shutdown", signame)
    try:
        # dispose DB connections/pools
        engine.dispose()
        logger.info("DB engine disposed")
    except Exception as e:
        logger.warning("Error disposing engine: %s", str(e))
    # set shutdown event for any running background tasks
    loop = asyncio.get_event_loop()
    loop.create_task(_set_shutdown())

async def _set_shutdown():
    shutdown_event.set()


# FastAPI startup/shutdown events
@app.on_event("startup")
async def startup_event():
    logger.info("Starting state-service")
    # Register signal handlers for graceful termination
    try:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: _handle_termination(s.name))
            except NotImplementedError:
                # add_signal_handler may not be implemented on Windows; fallback to signal.signal
                signal.signal(sig, lambda _signum, _frame, s=sig: _handle_termination(s.name))
    except Exception as e:
        logger.warning("Could not register signal handlers: %s", str(e))


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down state-service")
    try:
        engine.dispose()
    except Exception:
        logger.debug("Error disposing engine during shutdown")


# For manual run (development). In prod, run via uvicorn/gunicorn pointing to this module's 'app'.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("__main__:app", host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower())
