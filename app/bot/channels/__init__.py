from __future__ import annotations

import os
import asyncio
import signal
import logging
from logging.config import dictConfig
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry, multiprocess
from pydantic import BaseSettings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncConnection
from sqlalchemy import text
from pythonjsonlogger import jsonlogger

# Configuration via environment variables
class Settings(BaseSettings):
    SERVICE_NAME: str = "fastapi-microservice"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # App server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: Optional[str] = None  # e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # Gunicorn/Workers if used by container startup script
    WORKERS: int = 1

    class Config:
        env_file = ".env"

settings = Settings()

# Structured JSON logging setup
def configure_logging():
    level = settings.LOG_LEVEL.upper()
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d'
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # remove default handlers to avoid duplicate logs
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)

configure_logging()
logger = logging.getLogger(settings.SERVICE_NAME)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency in seconds", ["method", "path"])

# FastAPI App
app = FastAPI(title=settings.SERVICE_NAME, version="0.1.0")

# Database engine (async)
engine: Optional[AsyncEngine] = None
engine_lock = asyncio.Lock()
shutdown_event = asyncio.Event()

# Dependency to get a connection
async def get_connection() -> AsyncConnection:
    global engine
    if engine is None:
        raise HTTPException(status_code=503, detail="database not initialized")
    async with engine.connect() as conn:
        yield conn

# Middleware to collect metrics and logging
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    method = request.method
    path = request.url.path
    with REQUEST_LATENCY.labels(method=method, path=path).time():
        response = await call_next(request)
    status = str(response.status_code)
    REQUEST_COUNT.labels(method=method, path=path, status_code=status).inc()
    return response

@app.on_event("startup")
async def on_startup():
    global engine
    # initialize DB engine if DATABASE_URL provided
    if settings.DATABASE_URL:
        async with engine_lock:
            if engine is None:
                logger.info("Initializing database engine", extra={"db_url": settings.DATABASE_URL})
                # Configure connection pooling using SQLAlchemy async engine
                engine = create_async_engine(
                    settings.DATABASE_URL,
                    pool_size=settings.DB_POOL_SIZE,
                    max_overflow=settings.DB_MAX_OVERFLOW,
                    pool_timeout=settings.DB_POOL_TIMEOUT,
                    echo=False,
                    future=True,
                )
                # Test connection
                try:
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                    logger.info("Database connection test succeeded")
                except Exception:
                    logger.exception("Database connection test failed")
                    raise
    else:
        logger.info("No DATABASE_URL provided; DB features disabled")

    # Setup SIGTERM handler for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_shutdown_signal(s)))
        except NotImplementedError:
            # add_signal_handler may not be implemented on Windows
            logger.debug("Signal handlers not available on this platform")


async def _shutdown_signal(sig):
    logger.info("Received signal, initiating shutdown", extra={"signal": str(sig)})
    shutdown_event.set()
    # Dispose DB engine
    global engine
    if engine is not None:
        try:
            await engine.dispose()
            logger.info("Database engine disposed gracefully")
        except Exception:
            logger.exception("Error while disposing database engine")

    # allow uvicorn/gunicorn to handle the process exit after cleanup

@app.on_event("shutdown")
async def on_shutdown():
    global engine
    if engine is not None:
        try:
            await engine.dispose()
            logger.info("Database engine disposed on shutdown")
        except Exception:
            logger.exception("Problem disposing engine on shutdown")

# Health endpoint
@app.get("/health")
async def health():
    return JSONResponse({"status": "pass"})

# Readiness: checks DB connection if configured
@app.get("/readiness")
async def readiness():
    if settings.DATABASE_URL:
        global engine
        if engine is None:
            logger.warning("Readiness probe: DB engine not initialized")
            return JSONResponse({"status": "fail", "reason": "db not initialized"}, status_code=503)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready"})
        except Exception:
            logger.exception("Readiness probe: DB check failed")
            return JSONResponse({"status": "fail", "reason": "db check failed"}, status_code=503)
    else:
        # If no DB configured, consider service ready
        return JSONResponse({"status": "ready"})

# Example business endpoint that touches the DB
@app.get("/items/{item_id}")
async def read_item(item_id: int, conn: AsyncConnection = Depends(get_connection)):
    # This is a placeholder for real DB usage
    try:
        result = await conn.execute(text("SELECT :id as id"), {"id": item_id})
        row = result.first()
        return {"item_id": row._mapping['id'] if row is not None else None}
    except Exception:
        logger.exception("Error fetching item from DB")
        raise HTTPException(status_code=500, detail="internal error")

@app.get("/")
async def root():
    return JSONResponse({
        "service": settings.SERVICE_NAME,
        "environment": settings.ENVIRONMENT,
        "status": "running",
    })

# Prometheus metrics endpoint
@app.get("/metrics")
async def metrics():
    # If using Gunicorn with multiple processes, you may need to use the multiprocess mode
    resp = generate_latest()
    return PlainTextResponse(content=resp.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

# If running via `python -m app` we provide a small runner
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower())
