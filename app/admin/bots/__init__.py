from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseSettings
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

# NOTE: Place this file as service/__init__.py so the package name is `service`
# and you can run with `uvicorn service:app`.


class Settings(BaseSettings):
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: Optional[str] = None
    DB_POOL_MIN_SIZE: int = 1
    DB_POOL_MAX_SIZE: int = 10
    GRACEFUL_SHUTDOWN_SECONDS: int = 30
    METRICS_ENABLED: bool = True

    class Config:
        env_file = ".env"


settings = Settings()

# Structured JSON logging setup
logger = logging.getLogger("service")
logger.setLevel(settings.LOG_LEVEL.upper())
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)d"
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# Prometheus metrics
REQUEST_COUNT = Counter("service_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
DB_QUERIES = Counter("service_db_queries_total", "Total DB health check queries")

app = FastAPI(title="Service Microservice", version="1.0.0")

# Global connection pool
db_pool: Optional[asyncpg.pool.Pool] = None
# Event to coordinate graceful shutdown
_shutdown_event = asyncio.Event()


async def create_db_pool() -> Optional[asyncpg.pool.Pool]:
    if not settings.DATABASE_URL:
        logger.warning("No DATABASE_URL provided; skipping DB pool creation")
        return None
    try:
        pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=settings.DB_POOL_MIN_SIZE,
            max_size=settings.DB_POOL_MAX_SIZE,
        )
        logger.info("Database pool created", extra={"db_dsn": settings.DATABASE_URL})
        return pool
    except Exception as e:
        logger.exception("Failed to create DB pool: %s", str(e))
        raise


@app.on_event("startup")
async def startup() -> None:
    global db_pool
    logger.info("Starting up application")
    # Create DB pool if configured
    try:
        db_pool = await create_db_pool()
    except Exception:
        # If DB initialization fails, we still want the app to start for probe endpoints
        # but mark readiness accordingly via readiness endpoint.
        db_pool = None

    # register signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def _signal_handler(sig_num, frame):
        logger.info("Received signal %s, initiating graceful shutdown", sig_num)
        try:
            # schedule shutdown in loop
            loop.call_soon_threadsafe(_shutdown_event.set)
        except Exception:
            logger.exception("Failed to signal shutdown event")

    # Only register signals when running in main process
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError) as exc:
        logger.debug("Signal registration skipped: %s", exc)


@app.on_event("shutdown")
async def shutdown() -> None:
    global db_pool
    logger.info("Shutting down application")
    if db_pool is not None:
        try:
            await db_pool.close()
            logger.info("Database pool closed")
        except Exception:
            logger.exception("Error closing database pool")


# Middleware for structured request logging and metrics
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    logger.debug("incoming_request", extra={"method": request.method, "path": request.url.path})
    try:
        response: Response = await call_next(request)
    except Exception as exc:
        logger.exception("Unhandled exception while processing request: %s", str(exc))
        raise
    finally:
        pass

    # update prometheus metrics if enabled
    try:
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=str(response.status_code)).inc()
    except Exception:
        logger.debug("Could not update metrics for request")

    logger.info("request_complete", extra={"method": request.method, "path": request.url.path, "status_code": response.status_code})
    return response


@app.get("/", response_class=JSONResponse)
async def root():
    return {"message": "Service is running"}


@app.get("/health", response_class=JSONResponse)
async def health():
    # quick health check - should be lightweight and not depend on DB
    return {"status": "healthy"}


@app.get("/readiness", response_class=JSONResponse)
async def readiness():
    # readiness should ensure critical dependencies (DB) are available
    if settings.DATABASE_URL and db_pool is None:
        logger.warning("Readiness check failed: DB pool missing but DATABASE_URL configured")
        return JSONResponse(status_code=503, content={"status": "not ready", "reason": "db_unavailable"})

    # optionally perform a simple DB ping
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return {"status": "ready"}
        except Exception as e:
            logger.exception("Readiness DB check failed: %s", str(e))
            return JSONResponse(status_code=503, content={"status": "not ready", "reason": "db_query_failed"})

    return {"status": "ready"}


@app.get("/db-check", response_class=JSONResponse)
async def db_check():
    # explicit endpoint to check DB connection
    if db_pool is None:
        raise HTTPException(status_code=503, detail="DB not configured")
    try:
        DB_QUERIES.inc()
        async with db_pool.acquire() as conn:
            row = await conn.fetchval("SELECT 1")
        return {"db_ok": row == 1}
    except Exception as e:
        logger.exception("DB check failed: %s", str(e))
        raise HTTPException(status_code=500, detail="DB check failed")


@app.get("/metrics")
async def metrics():
    if not settings.METRICS_ENABLED:
        return PlainTextResponse("Metrics disabled", status_code=404)
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# Utility to wait for shutdown event (useful when running with python -m service)
async def _wait_for_shutdown():
    await _shutdown_event.wait()
    logger.info("Shutdown event detected; waiting %ss for graceful termination", settings.GRACEFUL_SHUTDOWN_SECONDS)
    await asyncio.sleep(settings.GRACEFUL_SHUTDOWN_SECONDS)


if __name__ == "__main__":
    # Allow running `python -m service` for local development
    import uvicorn

    config = {
        "host": settings.APP_HOST,
        "port": settings.APP_PORT,
        "log_level": settings.LOG_LEVEL.lower(),
        "loop": "asyncio",
        "lifespan": "on",
    }

    # Run uvicorn in the main thread and concurrently wait for a shutdown signal
    # When a signal occurs we set the _shutdown_event which allows graceful shutdown
    # configured in the container orchestration platform.
    logger.info("Starting uvicorn with config: %s", config)
    # Use uvicorn.run which blocks; the signal handlers in startup() will set _shutdown_event
    uvicorn.run("service:app", **config)
