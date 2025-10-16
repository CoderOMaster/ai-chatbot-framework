from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import logging
import os
import sys
import signal
import time
from typing import Generator

# ---------- Configuration from ENV ----------
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_URL = os.getenv("DB_URL", "sqlite:///./test.db")
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
REQUEST_METRICS = os.getenv("REQUEST_METRICS", "true").lower() in ("1", "true", "yes")

# ---------- Structured JSON logging ----------
logger = logging.getLogger("app")
log_handler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(LOG_LEVEL)

# ---------- Prometheus metrics ----------
REQUEST_COUNT = Counter("app_request_count", "Total request count", ["method", "endpoint", "http_status"]) if REQUEST_METRICS else None
REQUEST_LATENCY = Histogram("app_request_latency_seconds", "Request latency", ["method", "endpoint"]) if REQUEST_METRICS else None

# ---------- SQLAlchemy Engine (connection pooling) ----------
# Engine will be created at startup and disposed on shutdown
engine = None

app = FastAPI(title="example-microservice")

# Graceful shutdown flag
shutting_down = False


# ---------- Utility functions ----------
def create_db_engine():
    global engine
    # create_engine will manage a connection pool; config via env
    # For a production Postgres DB_URL like 'postgresql+psycopg2://user:pass@host:5432/dbname'
    try:
        # echo=False for production; set to True for dev debugging
        engine = create_engine(DB_URL, pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW, pool_pre_ping=True)
        logger.info("created db engine", extra={"db_url": DB_URL, "pool_size": POOL_SIZE, "max_overflow": MAX_OVERFLOW})
    except Exception as e:
        logger.exception("failed to create DB engine")
        raise


def dispose_db_engine():
    global engine
    if engine is not None:
        try:
            engine.dispose()
            logger.info("disposed db engine")
        except Exception:
            logger.exception("error disposing db engine")
        finally:
            engine = None


def check_db_connection(timeout_seconds: int = 5) -> bool:
    """Simple DB connectivity check used by readiness probe"""
    global engine
    if engine is None:
        logger.warning("check_db_connection: engine not initialized")
        return False

    try:
        with engine.connect() as conn:
            # lightweight query - works for most DBs
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.exception("db connection check failed")
        return False


# ---------- Dependency to get DB connection ----------
def get_db() -> Generator:
    """Yield a connection from the engine. Use in endpoints via Depends(get_db)."""
    global engine
    if engine is None:
        raise HTTPException(status_code=500, detail="Database engine is not initialized")

    conn = None
    try:
        conn = engine.connect()
        yield conn
    finally:
        if conn is not None:
            conn.close()


# ---------- Middleware: metrics + logging per request ----------
@app.middleware("http")
async def add_metrics_and_logging(request: Request, call_next):
    path = request.url.path
    method = request.method
    start = time.time()

    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as exc:
        status = 500
        logger.exception("Unhandled error in request", extra={"path": path, "method": method})
        raise
    finally:
        latency = time.time() - start
        # structured request log
        logger.info("request_finished", extra={
            "method": method,
            "path": path,
            "status": status,
            "latency_ms": int(latency * 1000)
        })
        if REQUEST_METRICS and REQUEST_COUNT and REQUEST_LATENCY:
            try:
                REQUEST_COUNT.labels(method=method, endpoint=path, http_status=str(status)).inc()
                REQUEST_LATENCY.labels(method=method, endpoint=path).observe(latency)
            except Exception:
                logger.exception("error updating prometheus metrics")

    return response


# ---------- App lifecycle events ----------
@app.on_event("startup")
async def on_startup():
    # establish DB engine
    create_db_engine()

    # register SIGTERM handler for graceful shutdown
    def _sigterm_handler(signum, frame):
        global shutting_down
        if shutting_down:
            return
        shutting_down = True
        logger.info("SIGTERM received, shutting down gracefully")
        try:
            dispose_db_engine()
        finally:
            # Exit process - uvicorn normally handles lifecycle, but ensure termination
            sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)
    logger.info("startup complete")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("shutdown event triggered")
    dispose_db_engine()


# ---------- Health and readiness endpoints ----------
@app.get("/health")
async def health():
    """Liveness probe - application running"""
    return JSONResponse({"status": "ok"})


@app.get("/readiness")
async def readiness():
    """Readiness probe - check dependent services like DB"""
    ok = check_db_connection()
    if ok:
        return JSONResponse({"status": "ready"})
    else:
        return JSONResponse({"status": "not ready"}, status_code=503)


# ---------- Metrics endpoint (Prometheus) ----------
@app.get("/metrics")
async def metrics():
    if not REQUEST_METRICS:
        return PlainTextResponse("Prometheus metrics disabled", status_code=404)
    try:
        data = generate_latest()
        return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
    except Exception:
        logger.exception("failed to generate metrics")
        return PlainTextResponse("error", status_code=500)


# ---------- Example API endpoint that uses DB connection ----------
@app.get("/")
async def index(db=Depends(get_db)):
    """Example endpoint showing a DB query. Keeps logic simple and portable."""
    try:
        # Different DB backends might return different result types; using text query
        result = db.execute(text("SELECT 1 as value"))
        row = result.first()
        val = row[0] if row is not None else None
        return {"message": "hello", "db_check": val}
    except SQLAlchemyError:
        logger.exception("db query failed")
        raise HTTPException(status_code=500, detail="db error")


# ---------- If run directly, start with Uvicorn (useful for local dev) ----------
if __name__ == "__main__":
    import uvicorn

    logger.info("starting uvicorn server", extra={"port": PORT})
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower())
