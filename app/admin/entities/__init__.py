from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Optional

import asyncpg
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

# __init__.py is intended to be the package entrypoint. The container runs the package as
# 'uvicorn app:app' where this file lives in /app/app/__init__.py in the container image.

APP_NAME = os.getenv("APP_NAME", "example-service")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_URL = os.getenv("DATABASE_URL")  # expected e.g. postgres://user:pass@host:5432/db
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
PROMETHEUS_ENABLED = os.getenv("PROMETHEUS_ENABLED", "true").lower() in ("1", "true", "yes")

# Basic structured JSON logging setup
logger = logging.getLogger(APP_NAME)
log_handler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d'
)
log_handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(log_handler)
logger.setLevel(LOG_LEVEL)

# FastAPI app
app = FastAPI(title=APP_NAME)

# Globals
_db_pool: Optional[asyncpg.pool.Pool] = None
_start_time = time.time()
_terminating = False
_terminate_event: Optional[asyncio.Event] = None

# Prometheus metrics (optional but enabled by default)
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    try:
        response: Response = await call_next(request)
        status_code = str(response.status_code)
    except Exception:
        status_code = "500"
        raise
    finally:
        elapsed = time.time() - start
        if PROMETHEUS_ENABLED:
            try:
                REQUEST_COUNT.labels(method=request.method, path=request.url.path, status=status_code).inc()
                REQUEST_LATENCY.labels(method=request.method, path=request.url.path).observe(elapsed)
            except Exception as e:  # protect metric recording from interfering with app
                logger.warning("Failed to record prometheus metric", exc_info=e)
    return response


@app.on_event("startup")
async def startup_event():
    global _db_pool, _terminate_event
    logger.info("Starting up", extra={"event": "startup"})

    # termination event used by signal handlers / background tasks
    _terminate_event = asyncio.Event()

    # Initialize DB pool if DATABASE_URL provided
    if DATABASE_URL:
        try:
            logger.info("Creating database pool", extra={"db": DATABASE_URL, "min": DB_POOL_MIN, "max": DB_POOL_MAX})
            _db_pool = await asyncpg.create_pool(
                dsn=DATABASE_URL,
                min_size=DB_POOL_MIN,
                max_size=DB_POOL_MAX,
                timeout=60.0,
            )
            logger.info("Database pool created", extra={"min": DB_POOL_MIN, "max": DB_POOL_MAX})
        except Exception:
            logger.exception("Failed to create database connection pool")
            # In many deployments you'd want startup to fail so orchestrator can backoff/retry
            raise
    else:
        logger.warning("No DATABASE_URL provided; DB-related readiness checks will fail")

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def _sigterm_handler():
        # This handler runs in event loop thread; schedule the shutdown
        nonlocal loop
        logger.info("SIGTERM received, scheduling shutdown", extra={"signal": "SIGTERM"})
        if _terminate_event and not _terminate_event.is_set():
            _terminate_event.set()

    # Register SIGTERM and SIGINT
    try:
        loop.add_signal_handler(signal.SIGTERM, _sigterm_handler)
        loop.add_signal_handler(signal.SIGINT, _sigterm_handler)
    except NotImplementedError:
        # add_signal_handler may not be available on Windows or some event loops
        logger.debug("Loop does not support add_signal_handler; relying on process signals")


@app.on_event("shutdown")
async def shutdown_event():
    global _db_pool
    logger.info("Shutting down", extra={"event": "shutdown"})
    if _db_pool:
        try:
            await _db_pool.close()
            logger.info("Database pool closed")
        except Exception:
            logger.exception("Error while closing database pool")


@app.get("/health")
async def health():
    """Liveness probe. Quick check that process is alive."""
    uptime = time.time() - _start_time
    return JSONResponse({"status": "ok", "uptime_seconds": round(uptime, 3)})


@app.get("/readiness")
async def readiness():
    """Readiness probe. Verifies essential dependencies (e.g., DB) are available."""
    # If DB is required for operation, ensure pool exists and a simple query works
    if DATABASE_URL:
        if not _db_pool:
            logger.warning("Readiness check failed: pool not initialized")
            return JSONResponse(status_code=503, content={"status": "unready", "reason": "db_pool_not_initialized"})
        try:
            async with _db_pool.acquire() as conn:
                # Basic validation: a very cheap query
                await conn.execute("SELECT 1")
        except Exception:
            logger.exception("Readiness check failed: DB test query failed")
            return JSONResponse(status_code=503, content={"status": "unready", "reason": "db_connection_failed"})

    # If more readiness checks are needed (e.g., cache, external APIs), add here
    return JSONResponse({"status": "ready"})


@app.get("/metrics")
async def metrics():
    if not PROMETHEUS_ENABLED:
        return PlainTextResponse("Prometheus metrics disabled", status_code=404)
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    return JSONResponse({"service": APP_NAME, "status": "running"})


# Example DB usage endpoint (shows connection pooling)
@app.get("/db-time")
async def db_time():
    """Example endpoint that uses a pooled DB connection to run a query."""
    if not DATABASE_URL:
        return JSONResponse(status_code=503, content={"error": "no_database_configured"})
    if not _db_pool:
        return JSONResponse(status_code=503, content={"error": "db_pool_not_initialized"})
    try:
        async with _db_pool.acquire() as conn:
            # show current DB time - builds confidence that DB connectivity works
            row = await conn.fetchrow("SELECT now() as now")
            return JSONResponse({"db_now": str(row["now"])})
    except Exception:
        logger.exception("DB endpoint failed")
        return JSONResponse(status_code=500, content={"error": "db_query_failed"})


# Provide an API to gracefully stop the app (for internal use only). This sets the terminate
# event which triggers shutdown handlers. Not exposed by default in public deployments.
@app.post("/internal/shutdown")
async def internal_shutdown():
    """Trigger graceful shutdown via HTTP (secured in production)."""
    global _terminate_event
    logger.info("/internal/shutdown called; setting terminate event")
    if _terminate_event and not _terminate_event.is_set():
        _terminate_event.set()
        return JSONResponse({"shutdown": "initiated"})
    return JSONResponse({"shutdown": "already_in_progress"})


# Background task to monitor terminate event and exit gracefully when set
@app.on_event("startup")
async def _terminate_watcher():
    # spawn a background task that waits for event and then triggers shutdown
    async def _watcher():
        global _terminate_event
        if not _terminate_event:
            return
        await _terminate_event.wait()
        logger.info("Terminate event set. Preparing to exit gracefully.")
        # give some time to finish in-flight requests / cleanup
        # In Kubernetes, make sure Pod terminationGracePeriodSeconds is configured
        try:
            # closing DB pool is handled in shutdown handler
            # Sleep briefly to allow other coroutines to finish
            await asyncio.sleep(float(os.getenv("GRACEFUL_SHUTDOWN_SECONDS", "5")))
        except asyncio.CancelledError:
            pass
        # Attempt to stop the loop after a short delay
        try:
            loop = asyncio.get_running_loop()
            loop.stop()
        except Exception:
            logger.debug("Could not stop loop programmatically; exiting process")
            # fallback
            os._exit(0)

    asyncio.create_task(_watcher())
