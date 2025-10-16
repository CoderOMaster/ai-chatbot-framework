import os
import signal
import sys
import time
import logging
from logging.config import dictConfig
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from jinja2 import Undefined
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry, multiprocess
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from pythonjsonlogger import jsonlogger

# --- Application utils (preserve original behavior) ---

def split_sentence(sentence: str):
    """Split a sentence by the original delimiter used in the legacy code."""
    return sentence.split("###")


class SilentUndefined(Undefined):
    """
    Class to suppress jinja2 errors and warnings
    Maintains the original logic from the legacy utils.py
    """

    def _fail_with_undefined_error(self, *args, **kwargs):
        return "undefined"

    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = __truediv__ = (
        __rtruediv__
    ) = __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = __pos__ = __neg__ = (
        __call__
    ) = __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __float__ = (
        __complex__
    ) = __pow__ = __rpow__ = _fail_with_undefined_error


# --- Configuration via environment variables ---
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_URL = os.getenv("DB_URL", "")  # e.g. postgresql+psycopg2://user:pass@host:5432/db
GRACEFUL_TIMEOUT = int(os.getenv("GRACEFUL_TIMEOUT", "10"))

# --- Structured JSON logging configuration ---
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s %(levelname)s %(name)s %(message)s")

def configure_logging():
    """Configure structured JSON logging for the microservice."""
    log_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    log_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.handlers = []
    root_logger.addHandler(log_handler)


configure_logging()
logger = logging.getLogger("ai_chatbot_utils_service")

# --- Prometheus metrics (basic) ---
REQUEST_COUNT = Counter("app_request_count", "Total HTTP requests", ["method", "endpoint", "http_status"])  # simple metric

# --- Database connection pooling (SQLAlchemy) ---
engine = None
if DB_URL:
    try:
        # tuned pool sizes; adjust per your environment
        engine = create_engine(
            DB_URL,
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
            pool_pre_ping=True,
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
        )
        logger.info("Database engine created", extra={"db_url": "REDACTED"})
    except Exception as e:
        logger.exception("Failed to create DB engine: %s", e)
        engine = None
else:
    logger.info("No DB_URL provided; DB features will be disabled.")

# --- FastAPI app ---
app = FastAPI(title="ai-chatbot-utils-service", version="1.0.0")

# Graceful shutdown handling
is_shutting_down = False


def _graceful_shutdown(signum, frame):
    global is_shutting_down
    logger.info("Received signal %s. Initiating graceful shutdown.", signum)
    is_shutting_down = True


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


# Middleware: logging requests and recording metrics
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
    except Exception as exc:
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=500).inc()
        logger.exception("Unhandled exception for request %s %s", request.method, request.url.path)
        raise
    latency = time.time() - start_time
    logger.info(
        "request_complete",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_seconds": latency,
        },
    )
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=response.status_code).inc()
    return response


# Root endpoint
@app.get("/", response_class=JSONResponse)
async def root():
    return {"service": "ai-chatbot-utils-service", "status": "running"}


# Health endpoint
@app.get("/health", response_class=JSONResponse)
def health():
    # quick liveness check
    return {"status": "healthy"}


# Readiness endpoint - checks DB connection if configured
@app.get("/readiness", response_class=JSONResponse)
def readiness():
    if is_shutting_down:
        logger.warning("Readiness probe: service is shutting down")
        raise HTTPException(status_code=503, detail="shutting_down")

    if engine is None:
        # If no DB configured we consider the app ready for non-DB workloads
        return {"ready": True, "db": "unconfigured"}

    try:
        with engine.connect() as conn:
            # cheap query
            conn.execute(text("SELECT 1"))
        return {"ready": True, "db": "ok"}
    except SQLAlchemyError as e:
        logger.exception("Readiness probe: DB connection failed")
        raise HTTPException(status_code=503, detail="db_unavailable")


# Endpoint to split sentences using preserved logic
@app.post("/split", response_class=JSONResponse)
async def split(payload: dict):
    sentence = payload.get("sentence") if payload else None
    if not sentence or not isinstance(sentence, str):
        raise HTTPException(status_code=400, detail="'sentence' string must be provided in JSON payload")
    parts = split_sentence(sentence)
    return {"original": sentence, "parts": parts}


# Metrics endpoint (Prometheus)
@app.get("/metrics")
async def metrics():
    try:
        data = generate_latest()
        return PlainTextResponse(content=data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        logger.exception("Failed to generate metrics: %s", e)
        raise HTTPException(status_code=500, detail="metrics_unavailable")


# DB health check endpoint (optional)
@app.get("/db/health", response_class=JSONResponse)
def db_health():
    if engine is None:
        raise HTTPException(status_code=404, detail="db_unconfigured")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"db": "ok"}
    except SQLAlchemyError:
        logger.exception("DB health check failed")
        raise HTTPException(status_code=503, detail="db_unavailable")


# Shutdown event to dispose engine gracefully
@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutdown event triggered. Cleaning up resources...")
    if engine is not None:
        try:
            engine.dispose()
            logger.info("Database engine disposed")
        except Exception:
            logger.exception("Error disposing database engine")
    logger.info("Shutdown complete")


# Custom exception handler to make structured errors
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTP error: %s %s", exc.status_code, exc.detail)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


# Entrypoint for container
def run():
    import uvicorn

    # Wait for graceful shutdown signal if present when running under PID 1 (optional)
    logger.info(
        "Starting ai-chatbot-utils-service", extra={"host": HOST, "port": PORT, "log_level": LOG_LEVEL}
    )

    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        log_config=None,
        access_log=False,
        workers=int(os.getenv("WORKERS", "1")),
    )


# Allow running as a module or using 'python app.py'
if __name__ == "__main__":
    # for uvicorn to import 'app' properly when this file is named app.py
    run()
