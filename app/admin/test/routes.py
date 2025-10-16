import os
import sys
import asyncio
import signal
import logging
import json
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

# External/internal imports used by original application
from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager
from app.bot.dialogue_manager.dialogue_manager import (
    DialogueManager,
    DialogueManagerException,
)

# Optional: DB + async session for connection pooling
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Optional: Redis
try:
    import aioredis
except Exception:
    aioredis = None

# Prometheus metrics (optional)
try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

    REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
    REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["endpoint"])
except Exception:
    REQUEST_COUNT = None
    REQUEST_LATENCY = None
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


# --------------------- Configuration ---------------------
class Settings(BaseModel):
    APP_ENV: str = os.getenv("APP_ENV", "production")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "5"))
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    READINESS_TIMEOUT_SEC: int = int(os.getenv("READINESS_TIMEOUT_SEC", "5"))


settings = Settings()


# --------------------- Logging (structured JSON) ---------------------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record_message = super().format(record)
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record_message,
        }
        # include extra attributes if any
        if hasattr(record, "extra"):
            payload.update(record.extra)
        return json.dumps(payload)


def configure_logging():
    root = logging.getLogger()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root.setLevel(level)

    handler = logging.StreamHandler(stream=sys.stdout)
    fmt = JsonFormatter()
    handler.setFormatter(fmt)
    root.handlers = [handler]


configure_logging()
logger = logging.getLogger("chat-service")


# --------------------- FastAPI App ---------------------
app = FastAPI(title="DialogueManager Microservice")
router = APIRouter(prefix="/test", tags=["test"])

# CORS - configurable via env later
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "*")],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Application state for shared resources
app.state.started = False
app.state.engine = None  # type: AsyncEngine | None
app.state.async_session = None  # type: sessionmaker | None
app.state.redis = None
app.state.shutdown_event = asyncio.Event()


# --------------------- Models ---------------------
class ChatRequest(BaseModel):
    thread_id: str
    text: str
    context: Dict[str, Any]


# --------------------- DB / Redis initialization ---------------------
async def init_db_pool(app: FastAPI) -> None:
    if not settings.DATABASE_URL:
        logger.info("no DATABASE_URL provided, skipping DB pool init")
        return

    logger.info("initializing DB engine", extra={"database_url": "[REDACTED]"})
    # Using SQLAlchemy async engine for connection pooling
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=10,
        pool_timeout=30,
        future=True,
        echo=False,
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.engine = engine
    app.state.async_session = async_session


async def init_redis(app: FastAPI) -> None:
    if not settings.REDIS_URL or aioredis is None:
        if settings.REDIS_URL:
            logger.warning("aioredis not installed, skipping redis init")
        else:
            logger.info("no REDIS_URL provided, skipping redis init")
        return
    try:
        app.state.redis = await aioredis.from_url(settings.REDIS_URL)
        logger.info("redis pool initialized")
    except Exception as e:
        logger.exception("failed to initialize redis", exc_info=e)
        app.state.redis = None


# --------------------- Dependencies ---------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the app-wide async sessionmaker (connection pooling).
    Internal code/components that need DB access can depend on this.
    """
    session_maker = app.state.async_session
    if session_maker is None:
        # DB not configured; raise or yield None depending on app design. We'll raise to make
        # the missing configuration explicit.
        raise HTTPException(status_code=503, detail="Database not configured")
    async with session_maker() as session:
        yield session


# --------------------- Health & Readiness ---------------------
@app.get("/health", response_class=JSONResponse, tags=["health"])
async def health() -> Dict[str, Any]:
    """Liveness probe - quick check that process is running."""
    return {"status": "ok"}


@app.get("/readiness", response_class=JSONResponse, tags=["health"])
async def readiness() -> Dict[str, Any]:
    """Readiness probe - ensure DB/redis or other critical dependencies are ready.
    If no DB/Redis configured, service is still ready as long as app started.
    """
    # If application is not fully started, return 503
    if not app.state.started:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "startup not complete"})

    # If DB configured, check connection
    if app.state.engine is not None:
        try:
            async with app.state.engine.connect() as conn:
                await conn.execute("SELECT 1")
        except Exception as e:
            logger.exception("readiness DB check failed")
            return JSONResponse(status_code=503, content={"ready": False, "reason": "db-connect-failed"})

    # If Redis configured, check ping
    if app.state.redis is not None:
        try:
            pong = await app.state.redis.ping()
            if not pong:
                raise RuntimeError("redis ping failed")
        except Exception:
            logger.exception("readiness redis check failed")
            return JSONResponse(status_code=503, content={"ready": False, "reason": "redis-unavailable"})

    return {"ready": True}


# Prometheus metrics endpoint (optional). Expose only if prometheus_client is installed
if generate_latest is not None:

    @app.get("/metrics")
    async def metrics() -> Response:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# --------------------- Router: chat endpoint (refactored) ---------------------
@router.post("/chat")
async def chat(
    body: ChatRequest,
    dialogue_manager: DialogueManager = Depends(get_dialogue_manager),
):
    """Endpoint to converse with the chatbot.
    Delegates the request processing to DialogueManager.

    Returns JSON response with the chatbot's reply and context.
    """
    # Structured log: incoming request
    logger.info("incoming_chat_request", extra={"thread_id": body.thread_id, "text_len": len(body.text)})

    user_message = UserMessage(thread_id=body.thread_id, text=body.text, context=body.context)

    # Metrics instrumentation optional
    if REQUEST_LATENCY is not None and REQUEST_COUNT is not None:
        with REQUEST_LATENCY.labels(endpoint="/test/chat").time():
            try:
                new_state = await dialogue_manager.process(user_message)
            except DialogueManagerException as e:
                REQUEST_COUNT.labels(method="POST", endpoint="/test/chat", http_status="400").inc()
                logger.exception("dialogue_manager_error", extra={"error": str(e)})
                raise HTTPException(status_code=400, detail=str(e))
    else:
        try:
            new_state = await dialogue_manager.process(user_message)
        except DialogueManagerException as e:
            logger.exception("dialogue_manager_error", extra={"error": str(e)})
            raise HTTPException(status_code=400, detail=str(e))

    result = new_state.to_dict()
    if REQUEST_COUNT is not None:
        REQUEST_COUNT.labels(method="POST", endpoint="/test/chat", http_status="200").inc()

    logger.info("chat_response_generated", extra={"thread_id": body.thread_id})

    return JSONResponse(content=result)


app.include_router(router)


# --------------------- Startup / Shutdown & Signal Handling ---------------------
async def _startup() -> None:
    logger.info("startup: initializing resources")
    # Initialize DB and Redis pools if configured
    await init_db_pool(app)
    await init_redis(app)

    # mark started after init
    app.state.started = True
    logger.info("startup: completed")


async def _shutdown() -> None:
    logger.info("shutdown: closing resources")
    # Close redis
    if getattr(app.state, "redis", None) is not None:
        try:
            await app.state.redis.close()
            logger.info("redis closed")
        except Exception:
            logger.exception("error closing redis")

    # Dispose engine
    if getattr(app.state, "engine", None) is not None:
        try:
            await app.state.engine.dispose()
            logger.info("db engine disposed")
        except Exception:
            logger.exception("error disposing engine")

    app.state.started = False
    app.state.shutdown_event.set()
    logger.info("shutdown: completed")


@app.on_event("startup")
async def on_startup() -> None:
    # register signal handlers for graceful shutdown if running outside uvicorn that may not handle them
    loop = asyncio.get_event_loop()

    # Some environments (like Windows) don't support add_signal_handler; guard against that
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown_signal_handler()))
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown_signal_handler()))
    except Exception:
        logger.debug("signal handlers not installed")

    await _startup()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await _shutdown()


async def shutdown_signal_handler() -> None:
    """Trigger graceful shutdown."""
    logger.info("received termination signal, starting graceful shutdown")
    try:
        await _shutdown()
    finally:
        # If running under an ASGI server, it should exit after completion
        # but make sure the process ends if shutdown takes too long
        try:
            # give event loop some time to finish pending tasks
            await asyncio.sleep(0.1)
        finally:
            logger.info("exiting process due to signal")
            # Use os._exit to force exit if needed; prefer graceful exit
            os._exit(0)


# --------------------- Entrypoint (for local debugging) ---------------------
def run() -> None:
    """Entrypoint for running via `python service.py`. In containers it's recommended to run via uvicorn.
    """
    import uvicorn

    uvicorn.run("service:app", host=settings.HOST, port=settings.PORT, log_config=None, log_level=settings.LOG_LEVEL.lower())


if __name__ == "__main__":
    run()
