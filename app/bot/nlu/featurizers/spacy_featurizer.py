from typing import Any, Dict, List, Optional
import os
import time
import signal
import logging
import json
from contextlib import contextmanager
from threading import Event

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

# Prometheus
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# SQLAlchemy used only to demonstrate connection pooling
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Try to import internal NLUComponent, otherwise provide a lightweight fallback so service can still run in isolation
try:
    from app.bot.nlu.pipeline import NLUComponent
except Exception:
    class NLUComponent:  # type: ignore
        """Fallback noop NLUComponent to allow local testing when internals are unavailable."""
        pass


# ----------------------
# Configuration via env
# ----------------------
SERVICE_HOST = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8000"))
SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_sm")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_URL = os.getenv("DATABASE_URL", "")  # e.g. postgresql://user:pass@host:5432/dbname
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

# Readiness timeout (seconds) for model load
MODEL_LOAD_TIMEOUT = int(os.getenv("MODEL_LOAD_TIMEOUT", "30"))


# ----------------------
# Structured JSON logging
# ----------------------
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": int(time.time()),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger("spacy-featurizer")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(LOG_LEVEL)


# ----------------------
# Prometheus metrics
# ----------------------
REQUEST_COUNT = Counter(
    "featurizer_requests_total", "Total number of featurizer requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram("featurizer_request_latency_seconds", "Latency of featurizer requests in seconds", ["endpoint"])
FEATURIZE_COUNT = Counter("featurize_processed_examples_total", "Number of examples featurized")


# ----------------------
# Models for API
# ----------------------
class Message(BaseModel):
    text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TrainPayload(BaseModel):
    training_data: List[Dict[str, Any]]


class FeaturizePayload(BaseModel):
    messages: Optional[List[Message]] = None
    message: Optional[Message] = None


# ----------------------
# SpacyFeaturizer class (keeps original logic but adapted for microservice)
# ----------------------
class SpacyFeaturizer(NLUComponent):
    """Spacy featurizer component that processes text and adds spacy features.

    In the original library the component adds a spaCy Doc object under key "spacy_doc".
    For transport over HTTP this service serializes the doc into a JSON-friendly format (tokens, lemmas, pos, ents).
    """

    def __init__(self, model_name: str):
        try:
            import spacy
        except Exception as e:
            logger.error(f"spaCy not available: {e}")
            raise

        # Load model once and reuse
        logger.info(f"Loading spaCy model '{model_name}'")
        self.tokenizer = spacy.load(model_name)
        logger.info("spaCy model loaded")

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            doc = self.tokenizer(example["text"])  # original internal doc
            example["spacy_doc"] = self._serialize_doc(doc)

    def load(self, model_path: str) -> bool:
        """Nothing to load from disk for this component in-service; model is loaded during init."""
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process text with spaCy and add serialized doc to message."""
        if not message.get("text"):
            return message

        doc = self.tokenizer(message["text"])
        message["spacy_doc"] = self._serialize_doc(doc)
        return message

    @staticmethod
    def _serialize_doc(doc) -> Dict[str, Any]:
        """Convert spaCy Doc into JSON-serializable structure.

        Keep a compact representation: tokens (text, lemma, pos, tag, dep), entities, and sentence boundaries.
        """
        tokens = [
            {
                "text": t.text,
                "lemma": t.lemma_,
                "pos": t.pos_,
                "tag": t.tag_,
                "dep": t.dep_,
            }
            for t in doc
        ]
        ents = [{"text": e.text, "label": e.label_, "start_char": e.start_char, "end_char": e.end_char} for e in doc.ents]
        sents = [s.text for s in doc.sents]
        return {"tokens": tokens, "ents": ents, "sents": sents}


# ----------------------
# Database connection pooling (SQLAlchemy engine example)
# ----------------------
def create_db_engine(db_url: str) -> Optional[Engine]:
    if not db_url:
        logger.info("No DATABASE_URL provided; skipping DB pool creation")
        return None

    try:
        engine = create_engine(db_url, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW)
        # Quick validation
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database engine created and validated")
        return engine
    except Exception as e:
        logger.error(f"Failed to create DB engine: {e}")
        raise


# ----------------------
# FastAPI app and lifecycle
# ----------------------
app = FastAPI(title="spaCy Featurizer", version="1.0")

# global instances
featurizer: Optional[SpacyFeaturizer] = None
db_engine: Optional[Engine] = None
shutdown_event = Event()
start_time = time.time()


@app.on_event("startup")
def startup_event():
    global featurizer, db_engine
    logger.info("Starting up spaCy Featurizer service")

    # Initialize DB pool (optional)
    try:
        db_engine = create_db_engine(DATABASE_URL)
    except Exception:
        # On startup we allow the service to continue if DB is not available (depending on your readiness policy)
        logger.exception("DB engine creation failed during startup")
        db_engine = None

    # Load spaCy model; ensure we fail if model cannot be loaded (so container will crash / restart)
    try:
        featurizer = SpacyFeaturizer(SPACY_MODEL)
    except Exception as e:
        logger.exception("Failed to load spaCy model on startup")
        # Re-raise so the container fails fast and Kubernetes can restart
        raise

    # Install SIGTERM handler to gracefully shutdown
    signal.signal(signal.SIGTERM, _handle_termination)


def _handle_termination(signum, frame):
    logger.info(f"Received signal {signum}; starting graceful shutdown")
    shutdown_event.set()


@app.on_event("shutdown")
def shutdown_event_handler():
    global db_engine
    logger.info("Shutting down spaCy Featurizer service")
    # Close DB engine gracefully
    try:
        if db_engine is not None:
            db_engine.dispose()
            logger.info("Database engine disposed")
    except Exception:
        logger.exception("Error while disposing DB engine")


# ----------------------
# Helper middleware-like utilities
# ----------------------
@contextmanager
def observe_request(endpoint: str):
    start = time.time()
    try:
        yield
        status_code = "200"
    except HTTPException as he:
        status_code = str(he.status_code)
        raise
    except Exception:
        status_code = "500"
        raise
    finally:
        elapsed = time.time() - start
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)
        # we don't have method and endpoint here; those are set per-route wrappers


# ----------------------
# Health / Readiness
# ----------------------
@app.get("/health")
def health():
    uptime = time.time() - start_time
    return JSONResponse({"status": "ok", "uptime_seconds": int(uptime)})


@app.get("/readiness")
def readiness():
    # Check that spaCy model is loaded and DB (if configured) is reachable
    ready = True
    reasons = []
    if featurizer is None:
        ready = False
        reasons.append("model_not_loaded")
    if DATABASE_URL and db_engine is None:
        # If DB configured but not ready
        ready = False
        reasons.append("db_unavailable")
    status_code = 200 if ready else 503
    return JSONResponse({"ready": ready, "reasons": reasons}, status_code=status_code)


# ----------------------
# Metrics endpoint
# ----------------------
@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ----------------------
# Featurize endpoint(s)
# ----------------------
@app.post("/featurize")
async def featurize(payload: FeaturizePayload, request: Request):
    method = request.method
    endpoint = request.url.path
    try:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status="200").inc()
        with REQUEST_LATENCY.labels(endpoint=endpoint).time():
            if featurizer is None:
                logger.error("Featurizer is not initialized")
                raise HTTPException(status_code=500, detail="Featurizer not initialized")

            to_process: List[Dict[str, Any]] = []
            if payload.message is not None:
                to_process.append(payload.message.dict())
            if payload.messages is not None:
                to_process.extend([m.dict() for m in payload.messages])

            results = []
            for msg in to_process:
                if not msg.get("text"):
                    results.append(msg)
                    continue
                processed = featurizer.process(msg)
                results.append(processed)
                FEATURIZE_COUNT.inc()

            return JSONResponse({"results": results})
    except HTTPException as he:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(he.status_code)).inc()
        raise
    except Exception as e:
        logger.exception("Unhandled error in /featurize")
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train")
async def train(payload: TrainPayload, request: Request):
    method = request.method
    endpoint = request.url.path
    try:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status="200").inc()
        with REQUEST_LATENCY.labels(endpoint=endpoint).time():
            if featurizer is None:
                logger.error("Featurizer is not initialized")
                raise HTTPException(status_code=500, detail="Featurizer not initialized")

            training_data = payload.training_data
            # Keep original behavior: add spacy_doc on each example
            featurizer.train(training_data, model_path="")
            return JSONResponse({"training_data": training_data})
    except HTTPException as he:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=str(he.status_code)).inc()
        raise
    except Exception as e:
        logger.exception("Unhandled error in /train")
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------
# Root / Info
# ----------------------
@app.get("/")
def root():
    return JSONResponse({"service": "spacy-featurizer", "model": SPACY_MODEL})


# ----------------------
# If run as main (development). Recommended to run via uvicorn in production.
# ----------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("spacy_featurizer_service:app", host=SERVICE_HOST, port=SERVICE_PORT, log_level=LOG_LEVEL)
