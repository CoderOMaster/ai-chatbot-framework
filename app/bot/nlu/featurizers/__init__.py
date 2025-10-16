import os
import signal
import asyncio
import logging
import time
from typing import Optional, List, Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from prometheus_client import CollectorRegistry
from prometheus_client import multiprocess

# Database connection pooling
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Internal import (keeps original language and logic)
from app.bot.nlu.featurizers.spacy_featurizer import SpacyFeaturizer

# Note: This module is intended to be imported by an ASGI server (uvicorn/gunicorn).
# It exposes `app` which can be served. File kept as __init__.py so package import remains compatible.

# -----------------------------
# Configuration via environment
# -----------------------------

SERVICE_NAME = os.getenv("SERVICE_NAME", "spacy-featurizer-service")
MODEL_NAME = os.getenv("MODEL_NAME", "en_core_web_sm")
MODEL_DOWNLOAD = os.getenv("MODEL_DOWNLOAD", "false").lower() in ("1", "true", "yes")
DB_URL = os.getenv("DB_URL", "")  # e.g. postgresql://user:pass@host:5432/db
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PORT = int(os.getenv("PORT", "8000"))
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("1", "true", "yes")

# SQLAlchemy pool tuning via env
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() in ("1", "true", "yes")

# -----------------------------
# Logging (structured JSON)
# -----------------------------

def configure_logging():
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    # remove other handlers if present to avoid duplicate logs in some environments
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)


configure_logging()
logger = logging.getLogger(SERVICE_NAME)

# -----------------------------
# Prometheus metrics
# -----------------------------

REQUEST_COUNT = Counter("spacy_requests_total", "Total requests to featurizer endpoint", ["method", "endpoint", "http_status"]) if METRICS_ENABLED else None
REQUEST_LATENCY = Histogram("spacy_request_latency_seconds", "Request latency in seconds", ["endpoint"]) if METRICS_ENABLED else None

# -----------------------------
# FastAPI app
# -----------------------------

app = FastAPI(title=SERVICE_NAME)

# Globals and state
nlp = None
featurizer: Optional[SpacyFeaturizer] = None
engine: Optional[Engine] = None
shutting_down = False

# Simple health flags
_model_loaded = False
_db_connected = False

# -----------------------------
# Models
# -----------------------------

class TextPayload(BaseModel):
    text: Optional[str] = None
    texts: Optional[List[str]] = None

class FeatureResponse(BaseModel):
    features: List[Any]
    model: str

# -----------------------------
# Utilities
# -----------------------------

async def _safe_run(func, *args, **kwargs):
    try:
        return await func(*args, **kwargs)
    except Exception:
        # synchronous fallback
        return func(*args, **kwargs)

# -----------------------------
# Startup / Shutdown
# -----------------------------

@app.on_event("startup")
async def startup_event():
    global nlp, featurizer, engine, _model_loaded, _db_connected

    logger.info("Starting up service", extra={"model": MODEL_NAME, "db_url_present": bool(DB_URL)})

    # Register signal handler for graceful shutdown
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(graceful_shutdown()))
    except Exception:
        # Not all environments allow setting signal handlers (e.g. Windows or some containers)
        logger.debug("Could not set loop signal handler for SIGTERM")

    # Optionally download model (if image does not include it)
    if MODEL_DOWNLOAD:
        logger.info("MODEL_DOWNLOAD is true. Attempting to download spaCy model at startup.")
        try:
            import spacy.cli
            spacy.cli.download(MODEL_NAME)
        except Exception as e:
            logger.warning("Failed to download spaCy model", extra={"error": str(e)})

    # Load spaCy model
    try:
        import spacy
        nlp = spacy.load(MODEL_NAME)
        # Instantiate internal featurizer with model (original module expected to be used this way).
        try:
            featurizer = SpacyFeaturizer(nlp)
        except Exception:
            # If featurizer has a different signature, attempt to instantiate without nlp
            try:
                featurizer = SpacyFeaturizer()
            except Exception as e:
                logger.exception("Failed to instantiate SpacyFeaturizer", exc_info=e)
                raise

        _model_loaded = True
        logger.info("spaCy model loaded", extra={"model": MODEL_NAME})
    except Exception as e:
        logger.exception("Failed to load spaCy model", exc_info=e)
        _model_loaded = False

    # Initialize DB engine with pooling if DB_URL provided
    if DB_URL:
        try:
            engine = create_engine(
                DB_URL,
                pool_size=DB_POOL_SIZE,
                max_overflow=DB_MAX_OVERFLOW,
                pool_pre_ping=DB_POOL_PRE_PING,
                future=True,
            )
            # quick connectivity test
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            _db_connected = True
            logger.info("Database connection established", extra={"db_url_present": True})
        except Exception as e:
            logger.exception("Database connection failed at startup", exc_info=e)
            engine = None
            _db_connected = False
    else:
        logger.info("No DB_URL configured. Skipping database initialization.")
        engine = None
        _db_connected = True  # mark true so readiness does not fail when DB not required


@app.on_event("shutdown")
async def shutdown_event():
    global engine, shutting_down
    shutting_down = True
    logger.info("Shutdown event triggered. Cleaning up resources...")
    # Close DB engine gracefully
    try:
        if engine is not None:
            engine.dispose()
            logger.info("Database engine disposed")
    except Exception:
        logger.exception("Error while disposing DB engine")

    # If featurizer needs cleanup, attempt to call it
    try:
        if hasattr(featurizer, "shutdown"):
            await _safe_run(featurizer.shutdown)
    except Exception:
        logger.exception("Error while shutting down featurizer")


async def graceful_shutdown():
    # Called on SIGTERM
    global shutting_down
    if shutting_down:
        return
    logger.info("SIGTERM received, initiating graceful shutdown")
    shutting_down = True
    # Wait briefly to allow in-flight requests to complete
    await asyncio.sleep(1)
    # Trigger FastAPI shutdown by calling lifespan shutdown hooks - depends on server
    # If running under uvicorn, sending SIGTERM to process is recommended; here we request event loop stop
    loop = asyncio.get_event_loop()
    loop.stop()

# -----------------------------
# Middleware-like monitoring
# -----------------------------

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        status_code = 500
        raise
    finally:
        latency = time.time() - start_time
        endpoint = request.url.path
        method = request.method
        if METRICS_ENABLED and REQUEST_COUNT and REQUEST_LATENCY:
            try:
                REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(status_code)).inc()
                REQUEST_LATENCY.labels(endpoint=endpoint).observe(latency)
            except Exception:
                logger.exception("Failed to observe metrics")
    return response

# -----------------------------
# Health and readiness
# -----------------------------

@app.get("/health", response_class=JSONResponse)
async def health():
    # Liveness: basic process check
    return JSONResponse(status_code=200, content={"status": "ok", "service": SERVICE_NAME})

@app.get("/readiness", response_class=JSONResponse)
async def readiness():
    # Readiness: ensure model loaded and DB (if required) reachable
    ok = True
    details: Dict[str, Any] = {"model_loaded": _model_loaded, "db_connected": _db_connected, "shutting_down": shutting_down}
    if not _model_loaded:
        ok = False
    if not _db_connected:
        ok = False
    status = 200 if ok and not shutting_down else 503
    return JSONResponse(status_code=status, content={"ready": ok, "details": details})

# -----------------------------
# Metrics endpoint
# -----------------------------

@app.get("/metrics")
async def metrics():
    if not METRICS_ENABLED:
        return PlainTextResponse("metrics disabled", status_code=404)
    try:
        # Use default registry
        data = generate_latest()
        return PlainTextResponse(data, media_type=CONTENT_TYPE_LATEST)
    except Exception:
        logger.exception("Error generating metrics")
        raise HTTPException(status_code=500, detail="metrics failure")

# -----------------------------
# Featurize endpoint
# -----------------------------

@app.post("/v1/featurize", response_model=FeatureResponse)
async def featurize(payload: TextPayload):
    if shutting_down:
        raise HTTPException(status_code=503, detail="shutting down")
    if not _model_loaded or featurizer is None:
        logger.warning("Featurizer not ready", extra={"model_loaded": _model_loaded})
        raise HTTPException(status_code=503, detail="model not loaded")

    texts: List[str] = []
    if payload.text:
        texts.append(payload.text)
    if payload.texts:
        texts.extend(payload.texts)
    if not texts:
        raise HTTPException(status_code=400, detail="no text provided")

    try:
        # Depending on implementation of SpacyFeaturizer, it might expose a `featurize` method.
        # We attempt to call common names. Keep the original logic but make it robust.
        features = []
        if hasattr(featurizer, "featurize"):
            for t in texts:
                out = featurizer.featurize(t)
                # If outputs are numpy arrays, convert to lists
                try:
                    import numpy as _np
                    if _np and hasattr(out, "tolist"):
                        out = out.tolist()
                except Exception:
                    pass
                features.append(out)
        elif hasattr(featurizer, "transform"):
            # e.g. batch transform
            out = featurizer.transform(texts)
            try:
                import numpy as _np
                if _np and hasattr(out, "tolist"):
                    out = out.tolist()
            except Exception:
                pass
            features = out
        else:
            # As a fallback, use the spaCy nlp pipeline directly
            for t in texts:
                doc = nlp(t)
                # Provide token vectors if available
                vec = getattr(doc, "vector", None)
                try:
                    import numpy as _np
                    if _np and hasattr(vec, "tolist"):
                        vec = vec.tolist()
                except Exception:
                    pass
                features.append(vec)

        return FeatureResponse(features=features, model=MODEL_NAME)
    except Exception as e:
        logger.exception("Error during featurization", exc_info=e)
        raise HTTPException(status_code=500, detail=str(e))

# Expose the app variable for ASGI servers

__all__ = ["app"]
