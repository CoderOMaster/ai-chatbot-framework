import os
import signal
import asyncio
import logging
import json
from typing import Dict, Any, Optional

from fastapi import FastAPI, APIRouter, UploadFile, File, Request
from fastapi.responses import Response, JSONResponse, PlainTextResponse
from pydantic import BaseSettings

# Optional imports used if available
try:
    import asyncpg
except Exception:
    asyncpg = None

try:
    from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
except Exception:
    Counter = None
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain"

# Keep the original store import
from app.admin.bots import store


class Settings(BaseSettings):
    SERVICE_NAME: str = "bots-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # DB connection for pooling (optional, depends on your stack)
    DATABASE_URL: Optional[str] = None
    DB_POOL_MIN_SIZE: int = 1
    DB_POOL_MAX_SIZE: int = 10

    # Graceful shutdown timeout in seconds
    SHUTDOWN_TIMEOUT: int = 10

    class Config:
        env_file = ".env"


settings = Settings()


# Simple JSON formatter
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # include extra keys if present
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            message.update(record.extra)
        return json.dumps(message)


# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(settings.LOG_LEVEL)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
root_logger.handlers = [handler]
logger = logging.getLogger(settings.SERVICE_NAME)


# Prometheus metrics (optional)
REQUEST_COUNTER = None
if Counter is not None:
    REQUEST_COUNTER = Counter(
        "bots_service_requests_total", "Total HTTP requests received", ["method", "path", "status"]
    )


app = FastAPI(title="Bots Service", version="1.0")
router = APIRouter(prefix="/bots", tags=["bots"])


# --- Application state helpers ---
async def _create_db_pool(app) -> Optional[object]:
    """
    Create and store a DB connection pool in app.state.db_pool if DATABASE_URL is provided and asyncpg is available.
    If your store manages its own pool (e.g. motor, aiomysql, SDKs), it will typically initialize itself.
    """
    if not settings.DATABASE_URL:
        logger.info(json.dumps({"event": "db_pool_skipped", "reason": "DATABASE_URL not set"}))
        return None

    if asyncpg is None:
        logger.warning(json.dumps({"event": "asyncpg_not_available", "reason": "asyncpg not installed"}))
        return None

    try:
        pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=settings.DB_POOL_MIN_SIZE,
            max_size=settings.DB_POOL_MAX_SIZE,
        )
        logger.info(json.dumps({"event": "db_pool_created"}))
        app.state.db_pool = pool
        return pool
    except Exception as e:
        logger.error(json.dumps({"event": "db_pool_error", "error": str(e)}))
        return None


async def _close_db_pool(app):
    pool = getattr(app.state, "db_pool", None)
    if pool is not None:
        try:
            await pool.close()
            logger.info(json.dumps({"event": "db_pool_closed"}))
        except Exception as e:
            logger.warning(json.dumps({"event": "db_pool_close_error", "error": str(e)}))


# --- Instrumentation middleware ---
@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        # Increment error metric if available
        if REQUEST_COUNTER is not None:
            try:
                REQUEST_COUNTER.labels(method=method, path=path, status="500").inc()
            except Exception:
                pass
        logger.exception("Unhandled exception during request")
        raise

    # Update prom metrics
    if REQUEST_COUNTER is not None:
        try:
            REQUEST_COUNTER.labels(method=method, path=path, status=str(status_code)).inc()
        except Exception:
            pass

    # Log simple request summary
    logger.info(json.dumps({"event": "request", "method": method, "path": path, "status": status_code}))
    return response


# --- Health and readiness endpoints ---
@app.get("/health", tags=["health"])
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/readiness", tags=["health"])
async def readiness():
    """
    Readiness checks should verify that the service can perform its primary function.
    We attempt to call store.health() if available or verify DB pool exists.
    """
    # If the store exposes a health check, prefer that
    try:
        health_fn = getattr(store, "health", None)
        if callable(health_fn):
            ok = await health_fn()
            return JSONResponse({"ready": bool(ok)})
    except Exception as e:
        logger.warning(json.dumps({"event": "store_health_check_failed", "error": str(e)}))

    # Fallback: check DB pool
    pool = getattr(app.state, "db_pool", None)
    if pool is not None:
        return JSONResponse({"ready": True})

    # If neither check exists, assume ready (to avoid blocking startup for stores that manage external resources)
    return JSONResponse({"ready": True})


# --- Prometheus metrics endpoint (optional) ---
if generate_latest is not None:

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        try:
            data = generate_latest()
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)
        except Exception:
            return PlainTextResponse("metrics generation failed", status_code=500)


# --- Bots API (refactored original routes) ---
@router.put("/{name}/config")
async def set_config(name: str, config: Dict[str, Any]):
    """
    Update bot config
    """
    # Keep behavior identical to original: call store.update_nlu_config
    await store.update_nlu_config(name, config)
    return {"message": "Config updated successfully"}


@router.get("/{name}/config")
async def get_config(name: str):
    """
    Get bot config
    """
    return await store.get_nlu_config(name)


@router.get("/{name}/export")
async def export_bot(name: str):
    """
    Export all intents and entities for the bot as a JSON file
    """
    data = await store.export_bot(name)
    return Response(
        content=json.dumps(data),
        media_type="application/json",
        headers={"Content-Disposition": "attachment;filename=chatbot_data.json"},
    )


@router.post("/{name}/import")
async def import_bot(name: str, file: UploadFile = File(...)):
    """
    Import intents and entities from a JSON file for the bot
    """
    content = await file.read()
    json_data = json.loads(content)
    return await store.import_bot(name, json_data)


app.include_router(router)


# --- Startup / Shutdown lifecycle ---
shutdown_event = asyncio.Event()


@app.on_event("startup")
async def startup():
    logger.info(json.dumps({"event": "startup", "service": settings.SERVICE_NAME}))

    # Create DB pool if configured
    pool = await _create_db_pool(app)

    # If store has an async initializer that accepts a pool or config, attempt to call it.
    # We try a few common function names so we don't enforce a change in store implementation.
    for init_name in ("init", "initialize", "connect", "init_pool"):
        init_fn = getattr(store, init_name, None)
        if callable(init_fn):
            try:
                # If init_fn is async, await it; else call it.
                if asyncio.iscoroutinefunction(init_fn):
                    # Try to provide pool if the function accepts it
                    try:
                        await init_fn(pool) if pool is not None else await init_fn()
                    except TypeError:
                        await init_fn()
                else:
                    try:
                        init_fn(pool) if pool is not None else init_fn()
                    except TypeError:
                        init_fn()
                logger.info(json.dumps({"event": "store_initialized", "fn": init_name}))
                break
            except Exception as e:
                logger.warning(json.dumps({"event": "store_init_failed", "fn": init_name, "error": str(e)}))

    # install SIGTERM handler to perform graceful shutdown
    loop = asyncio.get_event_loop()

    def _signal_handler(*_):
        logger.info(json.dumps({"event": "signal_received", "signal": "SIGTERM"}))
        # set the shutdown_event flag; uvicorn will handle terminating the server
        try:
            loop.create_task(_graceful_shutdown())
        except RuntimeError:
            # if loop closed or not running, ignore
            pass

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        logger.warning(json.dumps({"event": "signal_handler_not_installed"}))


async def _graceful_shutdown():
    """
    Perform graceful cleanup when SIGTERM is received.
    """
    logger.info(json.dumps({"event": "graceful_shutdown_start"}))
    try:
        # Call store shutdown helpers if present
        for close_name in ("close", "shutdown", "teardown", "close_pool"):
            close_fn = getattr(store, close_name, None)
            if callable(close_fn):
                try:
                    if asyncio.iscoroutinefunction(close_fn):
                        await close_fn()
                    else:
                        close_fn()
                    logger.info(json.dumps({"event": "store_closed", "fn": close_name}))
                except Exception as e:
                    logger.warning(json.dumps({"event": "store_close_failed", "fn": close_name, "error": str(e)}))

        await _close_db_pool(app)

    except Exception as e:
        logger.warning(json.dumps({"event": "graceful_shutdown_error", "error": str(e)}))
    finally:
        # give the server some time to finish
        await asyncio.sleep(settings.SHUTDOWN_TIMEOUT)
        shutdown_event.set()
        logger.info(json.dumps({"event": "graceful_shutdown_complete"}))


@app.on_event("shutdown")
async def shutdown():
    logger.info(json.dumps({"event": "shutdown", "service": settings.SERVICE_NAME}))
    # Ensure DB pool closed and store cleanup called
    await _close_db_pool(app)
    # attempt store cleanup as well (best-effort)
    close_fn = getattr(store, "close", None)
    if callable(close_fn):
        try:
            if asyncio.iscoroutinefunction(close_fn):
                await close_fn()
            else:
                close_fn()
        except Exception as e:
            logger.warning(json.dumps({"event": "store_close_error", "error": str(e)}))


# When run directly, start uvicorn programmatically
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
