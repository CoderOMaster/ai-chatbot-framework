import os
import asyncio
import signal
import time
import logging
from typing import Optional

import asyncpg
import structlog
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseSettings
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST


class Settings(BaseSettings):
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Database settings
    DATABASE_URL: Optional[str] = None  # e.g. postgres://user:pass@host:5432/db
    DB_POOL_MIN: int = 1
    DB_POOL_MAX: int = 10

    # Logging / runtime
    LOG_LEVEL: str = "INFO"
    METRICS_ENABLED: bool = True
    READINESS_GRACE_PERIOD: int = 2  # seconds to wait before shutting down after SIGTERM

    class Config:
        env_file = ".env"


settings = Settings()

# Structured JSON logging configuration (structlog)
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,  # include exc info
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)),
)
logger = structlog.get_logger()

app = FastAPI(title="microservice", version="1.0.0")

# Prometheus metrics (optional)
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"])
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency (seconds)", ["endpoint"])


# Middleware to collect metrics and structured logs for incoming requests
@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    start_time = time.time()
    path = request.url.path
    method = request.method

    logger.info("request.started", method=method, path=path)

    status_code = 500
    try:
        response = await call_next(request)
        status_code = getattr(response, "status_code", 200)
        return response
    except Exception as exc:
        logger.error("request.exception", method=method, path=path, error=str(exc))
        raise
    finally:
        latency = time.time() - start_time
        try:
            REQUEST_LATENCY.labels(path).observe(latency)
            REQUEST_COUNT.labels(method, path, str(status_code)).inc()
        except Exception:
            # Metrics should never bring down the app
            logger.exception("metrics.emit.failed")
        logger.info("request.finished", method=method, path=path, status=status_code, latency_s=latency)


# Application state: DB pool and readiness flag
@app.on_event("startup")
async def startup_event():
    # Install signal handlers here on the running loop
    loop = asyncio.get_running_loop()

    def _sigterm_handler():
        # Set readiness false quickly so orchestrator can stop sending traffic
        logger.info("sigterm.received", message="SIGTERM received — marking not ready")
        app.state.ready = False

        # allow other shutdown hooks to run; uvicorn/gunicorn will handle process exit

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _sigterm_handler)
        except NotImplementedError:
            # asyncio loop in Windows or some environments doesn't support add_signal_handler
            logger.debug("loop.add_signal_handler not implemented on this platform", signal=str(s))

    # Initialize DB pool if configured
    app.state.db_pool = None
    if settings.DATABASE_URL:
        try:
            logger.info("db.pool.creating", dsn=settings.DATABASE_URL, min=settings.DB_POOL_MIN, max=settings.DB_POOL_MAX)
            app.state.db_pool = await asyncpg.create_pool(
                dsn=settings.DATABASE_URL,
                min_size=settings.DB_POOL_MIN,
                max_size=settings.DB_POOL_MAX,
            )
            logger.info("db.pool.ready")
        except Exception as e:
            logger.exception("db.pool.creation.failed", error=str(e))
            # If DB is essential for your app, you might want to stop startup — we continue but mark not ready.

    # mark readiness only after initial setup
    app.state.ready = True
    logger.info("app.started", host=settings.APP_HOST, port=settings.APP_PORT)


@app.on_event("shutdown")
async def shutdown_event():
    # Clean up DB pool
    logger.info("app.shutting_down")
    app.state.ready = False

    pool = getattr(app.state, "db_pool", None)
    if pool:
        try:
            await pool.close()
            logger.info("db.pool.closed")
        except Exception:
            logger.exception("db.pool.close.failed")


# Health and readiness endpoints
@app.get("/health", tags=["health"])
async def health():
    # Liveness probe: simple check that the app process is up
    return JSONResponse({"status": "ok"})


@app.get("/readiness", tags=["health"])
async def readiness():
    # Readiness should reflect whether the app is prepared to accept traffic
    ready = getattr(app.state, "ready", False)
    if ready:
        return JSONResponse({"ready": True})
    else:
        # HTTP 503 signals orchestrator to stop sending traffic
        return JSONResponse({"ready": False}, status_code=503)


# Prometheus metrics endpoint
@app.get("/metrics", tags=["metrics"])
async def metrics():
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    data = generate_latest()
    return PlainTextResponse(content=data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


# Simple API endpoints for demonstration
@app.get("/", tags=["root"])
async def root():
    return JSONResponse({"message": "Hello from microservice", "version": "1.0.0"})


@app.get("/db/ping", tags=["db"])
async def db_ping():
    pool = getattr(app.state, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="database not configured")

    try:
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1")
            return JSONResponse({"db_ok": bool(val)})
    except Exception as e:
        logger.exception("db.ping.failed")
        raise HTTPException(status_code=500, detail="db ping failed")


# Example endpoint that echoes a posted message (keeps logic simple and stateless)
from pydantic import BaseModel


class EchoRequest(BaseModel):
    message: str


@app.post("/echo", tags=["demo"])
async def echo(payload: EchoRequest):
    logger.info("echo.received", message=payload.message)
    return JSONResponse({"echo": payload.message})


# If you want to run the app with `python -m package` where this file is the package __init__
# it's typical to run using an ASGI server like uvicorn or gunicorn + uvicorn workers.


# For local quick-testing (not for production):
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("__init__:app", host=settings.APP_HOST, port=settings.APP_PORT, log_level=settings.LOG_LEVEL.lower())
