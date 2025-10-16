import os
import signal
import logging
import asyncio
from typing import Dict, Any, Optional

import aiohttp
from aiohttp import ClientTimeout, TCPConnector
import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import uvicorn

# --- Configuration from environment variables ---
SERVICE_HOST = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
AIOHTTP_POOL_SIZE = int(os.getenv("AIOHTTP_POOL_SIZE", "100"))
DATABASE_URL = os.getenv("DATABASE_URL")  # Optional: postgres://user:pw@host:5432/db
ENABLE_PROMETHEUS = os.getenv("ENABLE_PROMETHEUS", "true").lower() in ("1", "true", "yes")

# --- Structured JSON logging setup ---
logger = logging.getLogger("http_client_service")
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(LOG_LEVEL)

# --- Prometheus metrics ---
REQUEST_COUNT = Counter(
    'api_requests_total', 'Total number of API requests', ['method', 'endpoint', 'http_status']
)
EXTERNAL_API_ERRORS = Counter('external_api_errors_total', 'Total external API call failures')
REQUEST_LATENCY = Histogram('api_request_latency_seconds', 'API request latency seconds', ['endpoint'])

# --- Exceptions ---
class APICallExcetion(Exception):
    """Preserved original exception name for backward compatibility."""
    pass

# --- FastAPI app ---
app = FastAPI(title="http-client-microservice")

# --- Global resources to be created on startup ---
app.state.aiohttp_session: Optional[aiohttp.ClientSession] = None
app.state.db_pool: Optional[asyncpg.pool.Pool] = None

# --- Original async call_api refactored to use shared session and connector ---
async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Asynchronously call external API with improved error handling and timeout management.
    Uses the shared aiohttp.ClientSession created at startup for connection pooling.
    """
    headers = headers or {}
    parameters = parameters or {}
    timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    # Use the shared session if available; else create a short-lived one
    session = app.state.aiohttp_session
    created_session = False
    if session is None:
        timeout_config = ClientTimeout(total=timeout)
        session = aiohttp.ClientSession(timeout=timeout_config, connector=TCPConnector(limit=AIOHTTP_POOL_SIZE))
        created_session = True

    try:
        method_up = method.upper()
        logger.debug(
            f"Initiating async API Call: url={url} method={method_up} payload={parameters}"
        )

        # Per-call timeout
        timeout_config = ClientTimeout(total=timeout)

        # Ensure we don't override session-level timeout incorrectly
        if method_up == "GET":
            async with session.get(url, headers=headers, params=parameters, timeout=timeout_config) as response:
                result = await response.json()
        elif method_up in ["POST", "PUT"]:
            kwargs = {"headers": headers}
            if is_json:
                kwargs["json"] = parameters
            else:
                kwargs["params"] = parameters
            async with getattr(session, method_up.lower())(url, timeout=timeout_config, **kwargs) as response:
                result = await response.json()
        elif method_up == "DELETE":
            async with session.delete(url, headers=headers, params=parameters, timeout=timeout_config) as response:
                result = await response.json()
        else:
            raise ValueError(f"Unsupported request method: {method_up}")

        response.raise_for_status()
        logger.debug("API response => %s", result)
        return result

    except aiohttp.ClientError as e:
        logger.error("HTTP error occurred: %s", str(e))
        EXTERNAL_API_ERRORS.inc()
        raise APICallExcetion(f"HTTP error occurred: {str(e)}")
    except asyncio.TimeoutError:
        logger.error("Request timed out after %s seconds", timeout)
        EXTERNAL_API_ERRORS.inc()
        raise APICallExcetion(f"Request timed out after {timeout} seconds")
    except Exception:
        logger.exception("Unexpected error during API call")
        EXTERNAL_API_ERRORS.inc()
        raise
    finally:
        if created_session:
            await session.close()

# --- FastAPI endpoints ---
@app.post("/call")
async def proxy_call(request: Request):
    """
    Proxy endpoint that accepts a JSON body describing the external call and returns the response.
    Expected JSON:
    {
      "url": "https://example.com/api",
      "method": "GET",
      "headers": { ... },
      "parameters": { ... },
      "is_json": true,
      "timeout": 10
    }
    """
    data = await request.json()
    url = data.get("url")
    method = data.get("method", "GET")
    headers = data.get("headers")
    parameters = data.get("parameters")
    is_json = data.get("is_json", False)
    timeout = data.get("timeout")

    if not url:
        raise HTTPException(status_code=400, detail="Missing 'url' in request body")

    with REQUEST_LATENCY.labels(endpoint="/call").time():
        try:
            result = await call_api(url, method, headers, parameters, is_json, timeout)
            REQUEST_COUNT.labels(method=method.upper(), endpoint="/call", http_status="200").inc()
            return JSONResponse(content=result)
        except APICallExcetion as e:
            logger.warning("External call failed: %s", str(e))
            REQUEST_COUNT.labels(method=method.upper(), endpoint="/call", http_status="502").inc()
            raise HTTPException(status_code=502, detail=str(e))
        except ValueError as e:
            logger.warning("Invalid request: %s", str(e))
            REQUEST_COUNT.labels(method=method.upper(), endpoint="/call", http_status="400").inc()
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("Unhandled error in /call")
            REQUEST_COUNT.labels(method=method.upper(), endpoint="/call", http_status="500").inc()
            raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health():
    """Liveness probe"""
    return JSONResponse(content={"status": "ok"})

@app.get("/readiness")
async def readiness():
    """Readiness probe: check DB pool (if configured) and aiohttp session"""
    checks = {"aiohttp_session": app.state.aiohttp_session is not None}
    if app.state.db_pool is not None:
        try:
            async with app.state.db_pool.acquire() as conn:
                await conn.execute('SELECT 1')
            checks["db"] = True
        except Exception:
            checks["db"] = False
    else:
        checks["db"] = None

    ready = all(v is True for v in checks.values() if v is not None)
    status = "ready" if ready else "not ready"
    return JSONResponse(content={"status": status, "checks": checks})

@app.get("/metrics")
async def metrics():
    if not ENABLE_PROMETHEUS:
        return PlainTextResponse("Prometheus disabled", status_code=404)
    data = generate_latest()
    return PlainTextResponse(content=data, media_type=CONTENT_TYPE_LATEST)

# --- Startup and shutdown handlers ---
@app.on_event("startup")
async def startup_event():
    logger.info("Starting service, creating aiohttp session and optional DB pool")

    # Create shared aiohttp session with connection pooling
    timeout_config = ClientTimeout(total=DEFAULT_TIMEOUT)
    connector = TCPConnector(limit=AIOHTTP_POOL_SIZE, enable_cleanup_closed=True)
    app.state.aiohttp_session = aiohttp.ClientSession(timeout=timeout_config, connector=connector)

    # Create DB pool if DATABASE_URL provided (Postgres via asyncpg)
    if DATABASE_URL:
        try:
            app.state.db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            logger.info("DB pool created")
        except Exception:
            logger.exception("Failed to create DB pool")
            # Continue startup even if DB pool creation fails; readiness will report failure

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down: closing aiohttp session and DB pool")
    if app.state.aiohttp_session is not None:
        await app.state.aiohttp_session.close()
        app.state.aiohttp_session = None
    if app.state.db_pool is not None:
        await app.state.db_pool.close()
        app.state.db_pool = None

# --- Graceful shutdown integration for SIGTERM/SIGINT when running uvicorn programmatically ---
def _install_signal_handlers(loop):
    signals = (signal.SIGINT, signal.SIGTERM)

    for s in signals:
        try:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(_shutdown(loop, s)))
        except NotImplementedError:
            # add_signal_handler may not be implemented on Windows with default event loop
            logger.warning("Signal handlers not fully supported on this platform")

async def _shutdown(loop, sig):
    logger.info(f"Received exit signal {sig.name}...")
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    logger.info("Cancelling outstanding tasks")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

# --- Entrypoint ---
if __name__ == "__main__":
    # When running directly, install signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    _install_signal_handlers(loop)

    uvicorn.run(
        "__main__:app",
        host=SERVICE_HOST,
        port=SERVICE_PORT,
        log_level=LOG_LEVEL.lower(),
        loop="asyncio",
    )
