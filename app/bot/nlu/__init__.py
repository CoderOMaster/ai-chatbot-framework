from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseSettings
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import logging
from pythonjsonlogger import jsonlogger
import os
import signal
import time
import asyncio
import uvicorn


class Settings(BaseSettings):
    APP_NAME: str = "nlp-microservice"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "info"
    APP_ENV: str = "production"
    DB_URL: str = "sqlite+pysqlite:///./app.db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    READINESS_DELAY_SECONDS: int = 0

    class Config:
        env_file = ".env"


settings = Settings()

# Configure structured JSON logging
logger = logging.getLogger(settings.APP_NAME)
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s'
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"],
)
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "HTTP request latency", ["endpoint"])

app = FastAPI(title=settings.APP_NAME)

# CORS (optional) - adjust origins as needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Readiness flag
app.state.ready = False
app.state.engine = None  # type: Engine | None


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    endpoint = request.url.path
    method = request.method
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        logger.exception("unhandled_exception", extra={"path": endpoint, "method": method})
        raise
    finally:
        latency = time.time() - start_time
        try:
            REQUEST_COUNT.labels(method, endpoint, str(status_code)).inc()
            REQUEST_LATENCY.labels(endpoint).observe(latency)
        except Exception:
            # Metrics should never break request flow
            logger.debug("metrics_error", exc_info=True)

    return response


@app.on_event("startup")
async def startup_event():
    """Initialize DB connections, metrics, and readiness state."""
    logger.info("startup_begin", extra={"env": settings.APP_ENV})

    # Initialize DB engine with connection pooling
    try:
        engine = create_engine(
            settings.DB_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
            future=True,
        )
        # simple connectivity check
        with engine.connect() as conn:
            # For SQLite this will create file and ensure connection works
            conn.execute(text("SELECT 1"))
        app.state.engine = engine
        logger.info("db_connected", extra={"db_url": settings.DB_URL})
    except Exception:
        logger.exception("db_connection_failed")
        # Keep app running but mark not ready
        app.state.engine = None

    # Optionally wait a bit before reporting ready (helps probe timing during startup)
    if settings.READINESS_DELAY_SECONDS > 0:
        await asyncio.sleep(settings.READINESS_DELAY_SECONDS)

    app.state.ready = True
    logger.info("startup_complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Dispose DB engine and cleanup."""
    logger.info("shutdown_begin")
    app.state.ready = False
    engine = app.state.engine
    if engine is not None:
        try:
            engine.dispose()
            logger.info("db_disposed")
        except Exception:
            logger.exception("db_dispose_failed")
    logger.info("shutdown_complete")


# Signal handling: mark app as not ready immediately on SIGTERM so kube can stop sending traffic
def _signal_handler(signum, frame):
    logger.info("signal_received", extra={"signal": signum})
    app.state.ready = False


# Register OS signal handlers
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


@app.get("/health")
async def health():
    """Liveness probe - indicates the process is alive."""
    return JSONResponse({"status": "ok"})


@app.get("/readiness")
async def readiness():
    """Readiness probe - indicates the app is ready to serve traffic."""
    if app.state.ready:
        return JSONResponse({"status": "ready"})
    else:
        return JSONResponse({"status": "not_ready"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    # Use default registry
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "env": settings.APP_ENV}


@app.get("/db/status")
async def db_status():
    """Simple DB status check that runs a test query."""
    engine = app.state.engine
    if engine is None:
        return JSONResponse({"db": "disconnected"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            ok = result.scalar()
            return {"db": "ok" if ok == 1 else "unknown"}
    except Exception:
        logger.exception("db_check_failed")
        return JSONResponse({"db": "error"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


if __name__ == "__main__":
    # Run uvicorn when invoked directly. In production you'd use an external process manager
    uvicorn.run(
        "__init__:app",
        host=settings.HOST,
        port=int(os.environ.get("PORT", settings.PORT)),
        log_level=settings.LOG_LEVEL,
        timeout_keep_alive=30,
    )
