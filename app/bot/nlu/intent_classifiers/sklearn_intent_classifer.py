import os
import sys
import signal
import time
import logging
from logging.config import dictConfig
from typing import Dict, Any, List, Optional
import cloudpickle
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import sqlalchemy
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry
from pythonjsonlogger import jsonlogger
import uvicorn

# Keep the original internal import reference (interface)
try:
    from app.bot.nlu.pipeline import NLUComponent
except Exception:  # pragma: no cover - if running standalone for testing
    class NLUComponent:
        """Fallback NLUComponent interface stub when internal package not available."""
        pass

# --------------------------- Configuration via ENV ---------------------------
MODEL_DIR = os.environ.get("MODEL_DIR", "/app/models")
MODEL_NAME = os.environ.get("MODEL_NAME", "sklearn_intent_model.hd5")
SPACY_MODEL = os.environ.get("SPACY_MODEL", "en_core_web_md")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
PORT = int(os.environ.get("PORT", "8000"))
METRICS_PATH = os.environ.get("METRICS_PATH", "/metrics")
DB_URL = os.environ.get("DB_URL", "")  # e.g. postgresql+psycopg2://user:pw@host/db
READINESS_FILE = os.environ.get("READINESS_FILE", "/tmp/ready")

# --------------------------- Structured JSON logging -------------------------
def configure_logging():
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove default handlers to avoid duplicated logs
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)
    root.addHandler(handler)


configure_logging()
logger = logging.getLogger(__name__)

# --------------------------- Prometheus metrics -----------------------------
REQUEST_COUNT = Counter(
    "sklearn_intent_requests_total", "Total requests to the sklearn intent microservice"
)
REQUEST_LATENCY = Histogram(
    "sklearn_intent_request_latency_seconds", "Latency of requests in seconds"
)

# --------------------------- DB Connection Pool -----------------------------
# Example connection pooling with SQLAlchemy. This is optional but included
# per requirements. If DB_URL is not set, no pool is created.
engine: Optional[sqlalchemy.engine.Engine] = None


def init_db_pool():
    global engine
    if not DB_URL:
        logger.info("No DB_URL configured; skipping DB pool initialization")
        return
    # Example pool settings. Tune pool_size and max_overflow for your workload.
    engine = sqlalchemy.create_engine(
        DB_URL,
        pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        pool_pre_ping=True,
    )
    logger.info("Initialized DB engine with pool")


def close_db_pool():
    global engine
    if engine is not None:
        engine.dispose()
        logger.info("Disposed DB engine pool")

# --------------------------- Request models ---------------------------------
class PredictRequest(BaseModel):
    text: str

# --------------------------- Original Class (adapted) -----------------------
class SklearnIntentClassifier(NLUComponent):
    """Sklearn-based intent classifier that implements NLUComponent interface.

    Adapted to be used inside a FastAPI microservice. Keeps original logic
    and file save/load format (cloudpickle).
    """

    INTENT_RANKING_LENGTH = 3

    def __init__(self, model_dir: str = MODEL_DIR, model_name: str = MODEL_NAME):
        self.model = None
        self.model_dir = model_dir
        self.model_name = model_name
        self.model_path = None

    def get_spacy_embedding(self, spacy_doc) -> np.ndarray:
        """
        Return spaCy vector for the given doc. Kept identical behavior to the
        original implementation which returned numpy array of doc.vector.
        """
        return np.array(spacy_doc.vector)

    def train(self, training_data: List[Dict[str, Any]], model_path: Optional[str] = None) -> None:
        """Train intent classifier for given training data

        This method is kept for completeness but in production training would
        usually be performed offline and the trained model baked into the
        container or stored in a model registry.
        """
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        X = []
        y = []
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            X.append(example.get("spacy_doc"))
            y.append(example.get("intent"))

        X = np.stack([self.get_spacy_embedding(example) for example in X])

        _, counts = np.unique(y, return_counts=True)
        cv_splits = max(2, min(5, np.min(counts) // 5))

        tuned_parameters = [
            {"C": [1, 2, 5, 10, 20, 100], "gamma": [0.1], "kernel": ["linear"]}
        ]

        classifier = GridSearchCV(
            SVC(C=1, probability=True, class_weight="balanced"),
            param_grid=tuned_parameters,
            n_jobs=-1,
            cv=cv_splits,
            scoring="f1_weighted",
            verbose=1,
        )

        classifier.fit(X, y)

        if model_path:
            path = os.path.join(model_path, self.model_name)
            with open(path, "wb") as f:
                cloudpickle.dump(classifier.best_estimator_, f)
            logger.info("Training completed & model written out to %s", path)

        self.model = classifier.best_estimator_

    def load(self, model_dir: Optional[str] = None) -> bool:
        """Load trained model from given path

        Returns True if model loaded successfully, False otherwise.
        """
        try:
            model_dir = model_dir or self.model_dir
            path = os.path.join(model_dir, self.model_name)
            with open(path, "rb") as f:
                self.model = cloudpickle.load(f)
            self.model_path = path
            logger.info("Loaded model from %s", path)
            return True
        except Exception as e:
            logger.exception("Failed loading model: %s", str(e))
            return False

    def predict_proba(self, spacy_doc) -> (np.ndarray, np.ndarray):
        """Given a spaCy doc, return sorted indices and probabilities.

        The original method expected X containing spacy_doc under key 'spacy_doc'.
        Here we accept a spaCy doc directly.
        """
        if self.model is None:
            raise RuntimeError("Model is not loaded")

        pred_result = self.model.predict_proba([self.get_spacy_embedding(spacy_doc)])
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.

        Expects message to contain keys: 'text' and 'spacy_doc'.
        Returns message augmented with 'intent' and 'intent_ranking'.
        """
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking = []

        if self.model:
            intents, probabilities = self.predict_proba(message.get("spacy_doc"))
            intents = [self.model.classes_[intent] for intent in intents.flatten()]
            probabilities = probabilities.flatten()

            if len(intents) > 0 and len(probabilities) > 0:
                ranking = list(zip(list(intents), list(probabilities)))
                ranking = ranking[: self.INTENT_RANKING_LENGTH]

                intent = {"intent": intents[0], "confidence": float(probabilities[0])}
                intent_ranking = [
                    {"intent": intent_name, "confidence": float(score)}
                    for intent_name, score in ranking
                ]
            else:
                intent = {"name": None, "confidence": 0.0}
                intent_ranking = []

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message

# --------------------------- FastAPI App ------------------------------------
app = FastAPI(title="sklearn-intent-classifier")

# We'll lazily import spaCy on startup to avoid heavy import during cold start
spacy = None
nlp = None
classifier: Optional[SklearnIntentClassifier] = None

# Readiness state file management (optional): create file when ready

def mark_ready():
    try:
        with open(READINESS_FILE, "w") as fh:
            fh.write("ready")
    except Exception:
        # Not fatal
        pass


def unmark_ready():
    try:
        if os.path.exists(READINESS_FILE):
            os.remove(READINESS_FILE)
    except Exception:
        pass


@app.on_event("startup")
def startup_event():
    global spacy, nlp, classifier
    logger.info("Starting sklearn-intent-classifier microservice")

    # Initialize DB pool if configured
    try:
        init_db_pool()
    except Exception:
        logger.exception("DB pool initialization failed")

    # Load spaCy model
    try:
        import importlib
        spacy = importlib.import_module("spacy")
        nlp = spacy.load(SPACY_MODEL)
        logger.info("Loaded spaCy model: %s", SPACY_MODEL)
    except Exception as e:
        logger.exception("Failed to load spaCy model '%s': %s", SPACY_MODEL, e)
        # In some deployments spaCy model is heavy — we allow the service to start
        # but prediction will raise until model is fixed.

    # Initialize classifier and load model
    classifier = SklearnIntentClassifier(model_dir=MODEL_DIR, model_name=MODEL_NAME)
    loaded = classifier.load(MODEL_DIR)
    if not loaded:
        logger.warning("Model not loaded from %s. Predictions will fail until model is available.", MODEL_DIR)

    # Mark readiness
    mark_ready()


@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutdown: cleaning up resources")
    # Close DB pools
    try:
        close_db_pool()
    except Exception:
        logger.exception("Error while closing DB pool")
    # Unmark readiness
    unmark_ready()


# SIGTERM handling for graceful termination
def _graceful_shutdown(signum, frame):
    logger.info("Received signal %s, exiting...", signum)
    # FastAPI/uvicorn will call shutdown handlers on SIGTERM by default; we just ensure cleanup
    try:
        unmark_ready()
        close_db_pool()
    except Exception:
        logger.exception("Error during graceful shutdown")
    # Give some time for cleanups (can be adjusted)
    time.sleep(1)
    sys.exit(0)


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)

# --------------------------- API Endpoints ---------------------------------

@app.get("/health")
def health():
    """Liveness probe"""
    return JSONResponse({"status": "ok"})


@app.get("/readiness")
def readiness():
    """Readiness probe: rely on presence of readiness file if configured.

    If READINESS_FILE is not set or not writable, fall back to checking model loaded.
    """
    try:
        if os.path.exists(READINESS_FILE):
            return JSONResponse({"ready": True})
    except Exception:
        pass

    # Fallback: check classifier and spaCy are loaded
    ready = (classifier is not None and classifier.model is not None and nlp is not None)
    return JSONResponse({"ready": ready})


@app.post("/predict")
def predict(req: PredictRequest, request: Request):
    """Predict endpoint: accepts a JSON body {"text": "..."} and returns
    the message augmented with 'intent' and 'intent_ranking'.
    """
    REQUEST_COUNT.inc()
    start = time.time()
    try:
        # Ensure spaCy model is available
        if nlp is None:
            logger.error("spaCy model not available for embedding")
            raise HTTPException(status_code=500, detail="spaCy model not loaded")

        if classifier is None or classifier.model is None:
            logger.error("Classifier model not loaded")
            raise HTTPException(status_code=503, detail="Model not available")

        doc = nlp(req.text)
        message = {"text": req.text, "spacy_doc": doc}
        result = classifier.process(message)
        return JSONResponse(result)
    finally:
        REQUEST_LATENCY.observe(time.time() - start)


@app.get(METRICS_PATH)
def metrics():
    """Expose Prometheus metrics (if prometheus_client included)."""
    registry = CollectorRegistry()
    # By default generate_latest uses the global registry. To keep it simple,
    # use the default. (Alternatively, we could pass custom registry.)
    data = generate_latest()
    return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


# Simple health-check root
@app.get("/")
def root():
    return {"service": "sklearn-intent-classifier", "status": "running"}

# --------------------------- CLI Entrypoint --------------------------------
if __name__ == "__main__":
    # uvicorn is recommended as ASGI server. We configure a graceful loop.
    uvicorn.run(
        "sklearn_intent_classifer:app",
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        # number of workers should be configured by container orchestrator
    )
