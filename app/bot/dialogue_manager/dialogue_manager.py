import os
import sys
import json
import signal
import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from jinja2 import Template

# Prometheus (optional)
from prometheus_client import Counter, Summary, generate_latest, CONTENT_TYPE_LATEST

# Internal app imports (preserved from original project)
from app.admin.bots.store import get_bot
from app.admin.intents.store import list_intents
from app.bot.memory import MemorySaver
from app.bot.memory.memory_saver_mongo import MemorySaverMongo
from app.bot.memory.models import State
from app.bot.nlu.pipeline import NLUPipeline
from app.bot.nlu.pipeline_utils import get_pipeline
from app.bot.dialogue_manager.utils import SilentUndefined, split_sentence
from app.bot.dialogue_manager.models import (
    IntentModel,
    ParameterModel,
    UserMessage,
)
from app.bot.dialogue_manager.http_client import call_api, APICallExcetion
from app.config import app_config
from app.database import client as default_db_client

# Environment variables
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SERVE_METRICS = os.getenv("SERVE_METRICS", "true").lower() in ("1", "true", "yes")
MONGO_URI = os.getenv("MONGO_URI", None)
MONGO_MAX_POOL_SIZE = int(os.getenv("MONGO_MAX_POOL_SIZE", "50"))
WORKERS = int(os.getenv("WORKERS", "1"))

# Prometheus metrics
REQUEST_COUNT = Counter("dialogue_manager_requests_total", "Total request count", ["endpoint", "method", "status"])
REQUEST_LATENCY = Summary("dialogue_manager_request_latency_seconds", "Request latency in seconds", ["endpoint"])

# JSON structured logging setup
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # include any extra fields
        if hasattr(record, "extra"):
            payload.update(record.extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger("dialogue_manager_service")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(LOG_LEVEL)

# Reuse original DialogueManager class with minimal adaptation for DI and logging
class DialogueManagerException(Exception):
    pass

class DialogueManager:
    def __init__(
        self,
        memory_saver: MemorySaver,
        intents: List[IntentModel],
        nlu_pipeline: NLUPipeline,
        fallback_intent_id: str,
        intent_confidence_threshold: float,
    ):
        self.memory_saver = memory_saver
        self.nlu_pipeline = nlu_pipeline
        self.intents = {intent.intent_id: intent for intent in intents}
        self.fallback_intent_id = fallback_intent_id
        self.confidence_threshold = intent_confidence_threshold

    @classmethod
    async def from_config(cls, db_client=None):
        """
        Initialize DialogueManager with all required dependencies (async).
        """
        logger.info("Loading intents and initializing NLU pipeline", extra={})

        db_intents = await list_intents()
        intents = [IntentModel.from_db(intent) for intent in db_intents]

        nlu_pipeline = await get_pipeline()

        fallback_intent_id = app_config.DEFAULT_FALLBACK_INTENT_NAME

        bot = await get_bot("default")
        confidence_threshold = (
            bot.nlu_config.traditional_settings.intent_detection_threshold
        )

        # If a db_client is passed (e.g., created with pooling), use it, else fallback to default import
        mongo_client = db_client or default_db_client
        memory_saver = MemorySaverMongo(mongo_client)

        return cls(
            memory_saver,
            intents,
            nlu_pipeline,
            fallback_intent_id,
            confidence_threshold,
        )

    def update_model(self, models_dir):
        ok = self.nlu_pipeline.load(models_dir)
        if not ok:
            self.nlu_pipeline = None
        logger.info("NLU Pipeline models updated")

    async def process(self, message: UserMessage) -> State:
        if self.nlu_pipeline is None:
            raise DialogueManagerException(
                "NLU pipeline is not initialized. Please build the models."
            )

        current_state = await self.memory_saver.get(message.thread_id)

        if not current_state:
            logger.debug(f"No current state found for thread_id: {message.thread_id}, creating new state")
            current_state = await self.memory_saver.init_state(message.thread_id)

        current_state.update(message)

        try:
            nlu_result = self.nlu_pipeline.process({"text": current_state.user_message.text})

            query_intent_id, _ = self._get_intent_id_and_confidence(current_state, nlu_result)

            query_intent = self._get_intent(query_intent_id)
            if query_intent is None:
                query_intent = self._get_fallback_intent()

            current_state.nlu = {"entities": nlu_result.get("entities"), "intent": nlu_result.get("intent")}

            active_intent_id = current_state.get_active_intent_id()
            if active_intent_id and query_intent_id != active_intent_id:
                active_intent = self._get_intent(current_state.intent["id"])
            else:
                active_intent = query_intent

            current_state, active_intent = self._process_intent(query_intent, active_intent, current_state)
            current_state.intent = {"id": active_intent.intent_id}

            if current_state.complete:
                current_state = await self._handle_api_trigger(active_intent, current_state)

            logger.debug(f"Processed input: {current_state.thread_id}", extra=current_state.to_dict())

            await self.memory_saver.save(message.thread_id, current_state)

            return current_state

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            raise

    def _get_intent_id_and_confidence(self, current_state: State, nlu_result: Dict) -> Tuple[str, float]:
        input_text = current_state.user_message.text
        if input_text.startswith("/"):
            intent_id = input_text.split("/")[1]
            confidence = 1.0
        else:
            predicted = nlu_result["intent"]
            if predicted["confidence"] < self.confidence_threshold:
                return self.fallback_intent_id, 1.0
            else:
                return predicted["intent"], predicted["confidence"]
        return intent_id, confidence

    def _get_intent(self, intent_id: str) -> Optional[IntentModel]:
        return self.intents.get(intent_id)

    def _get_fallback_intent(self) -> IntentModel:
        return self.intents[self.fallback_intent_id]

    def _process_intent(self, query_intent: IntentModel, active_intent: IntentModel, current_state: State) -> Tuple[State, IntentModel]:
        if query_intent.intent_id == "cancel":
            active_intent = query_intent
            current_state.complete = True
            current_state.parameters = []
            current_state.extracted_parameters = {}
            current_state.missing_parameters = []
            current_state.current_node = None
            return current_state, active_intent

        parameters = active_intent.parameters

        if parameters:
            extracted_entities = current_state.nlu.get("entities", {})

            entities_by_type = {}
            for entity_name, entity_value in extracted_entities.items():
                if entity_name not in entities_by_type:
                    entities_by_type[entity_name] = []
                entities_by_type[entity_name].append(entity_value)

            if len(current_state.parameters) == 0:
                for param in parameters:
                    current_state.parameters.append({
                        "name": param.name,
                        "type": param.type,
                        "required": param.required,
                    })

            for param in parameters:
                if (param.type == "free_text" and current_state.current_node == param.name):
                    current_state.extracted_parameters[param.name] = current_state.user_message.text
                    continue
                else:
                    if param.type in entities_by_type and entities_by_type[param.type]:
                        current_state.extracted_parameters[param.name] = entities_by_type[param.type].pop(0)

            current_state = self._handle_missing_parameters(parameters, current_state)

        current_state.complete = not current_state.missing_parameters
        return current_state, active_intent

    def _handle_missing_parameters(self, parameters: List[ParameterModel], current_state: State) -> State:
        missing_parameters = []
        current_state.missing_parameters = []

        current_state.current_node = None
        current_state.bot_message = []

        for parameter in parameters:
            if parameter.required and parameter.name not in current_state.extracted_parameters:
                current_state.missing_parameters.append(parameter.name)
                missing_parameters.append(parameter)

        if missing_parameters:
            current_node = missing_parameters[0]
            current_state.current_node = current_node.name
            current_state.bot_message = [{"text": msg} for msg in split_sentence(current_node.prompt)]
        return current_state

    async def _handle_api_trigger(self, intent: IntentModel, current_state: State) -> State:
        if intent.api_trigger and intent.api_details:
            try:
                result = await self._call_intent_api(intent, current_state)
                template = Template(intent.speech_response, undefined=SilentUndefined, enable_async=True)
                rendered_text = await template.render_async(context=current_state.context, parameters=current_state.extracted_parameters, result=result)

                current_state.bot_message = [{"text": msg} for msg in split_sentence(rendered_text)]

            except DialogueManagerException as e:
                logger.warning(f"API call failed: {e}")
                current_state.bot_message = [{"text": "Service is not available. Please try again later."}]
        else:
            template = Template(intent.speech_response, undefined=SilentUndefined, enable_async=True)
            rendered_text = await template.render_async(context=current_state.context, parameters=current_state.extracted_parameters)
            current_state.bot_message = [{"text": msg} for msg in split_sentence(rendered_text)]
        return current_state

    async def _call_intent_api(self, intent: IntentModel, current_state: State):
        api_details = intent.api_details
        headers = api_details.get_headers()
        url_template = Template(api_details.url, undefined=SilentUndefined)
        rendered_url = url_template.render(context=current_state.context, parameters=current_state.extracted_parameters)
        if api_details.is_json:
            request_template = Template(api_details.json_data, undefined=SilentUndefined)
            request_json = request_template.render(context=current_state.context, parameters=current_state.extracted_parameters)
            parameters = json.loads(request_json)
        else:
            parameters = current_state.extracted_parameters

        try:
            return await call_api(rendered_url, api_details.request_type, headers, parameters, api_details.is_json)
        except APICallExcetion as e:
            logger.warning(f"API call failed: {e}")
            raise DialogueManagerException("API call failed")


# FastAPI application
app = FastAPI(title="Dialogue Manager Service", version="1.0")

# Allow CORS if required via env
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
if ALLOWED_ORIGINS:
    if ALLOWED_ORIGINS == "*":
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    else:
        origins = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# store service components in app.state
app.state.dialogue_manager = None
app.state.db_client = None

# Create a Mongo client with pooling if MONGO_URI provided; otherwise use default_db_client
def create_db_client() -> object:
    try:
        from pymongo import MongoClient
    except Exception as e:
        logger.error("pymongo is required for MongoDB support", exc_info=True)
        raise

    uri = MONGO_URI or os.getenv("MONGO_URI")
    if not uri:
        # fallback to default client imported from app.database if available
        logger.warning("MONGO_URI not set, falling back to default app.database.client")
        return default_db_client

    client = MongoClient(uri, maxPoolSize=MONGO_MAX_POOL_SIZE)
    # Optional: set app name
    try:
        client.admin.command("ping")
    except Exception:
        logger.warning("Unable to ping MongoDB with new client; continuing but readiness may fail")
    return client


@app.on_event("startup")
async def on_startup():
    logger.info("Starting Dialogue Manager service")

    # Create DB client with pooling
    try:
        db_client = create_db_client()
        app.state.db_client = db_client
    except Exception as e:
        logger.error("Failed to create DB client", exc_info=True)
        raise

    # Build DialogueManager instance
    try:
        dm = await DialogueManager.from_config(db_client=db_client)
        app.state.dialogue_manager = dm
        logger.info("DialogueManager instance created and ready")
    except Exception:
        logger.exception("Failed to initialize DialogueManager")
        raise


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down Dialogue Manager service")
    # Attempt to close DB client cleanly
    db_client = app.state.db_client
    if db_client is not None:
        try:
            # pymongo MongoClient.close() is safe to call
            db_client.close()
            logger.info("Closed DB client")
        except Exception:
            logger.exception("Error closing DB client")


# Graceful SIGTERM handling for non-uvicorn orchestrators
stop_event = asyncio.Event()

def _signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, setting stop event")
    try:
        stop_event.set()
    except Exception:
        pass

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# Health endpoints
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})


@app.get("/readiness")
async def readiness():
    # Readiness checks: DialogueManager loaded, NLU pipeline loaded, DB reachable
    dm = app.state.dialogue_manager
    db_client = app.state.db_client

    ready = True
    details = {}

    if dm is None:
        ready = False
        details["dialogue_manager"] = "missing"
    else:
        details["dialogue_manager"] = "ok"
        if getattr(dm, "nlu_pipeline", None) is None:
            ready = False
            details["nlu_pipeline"] = "not_loaded"
        else:
            details["nlu_pipeline"] = "ok"

    # Check DB ping (do not block; run in thread)
    try:
        if db_client is not None:
            loop = asyncio.get_event_loop()
            def ping():
                try:
                    db_client.admin.command("ping")
                    return True
                except Exception:
                    return False
            ping_ok = await loop.run_in_executor(None, ping)
            details["db_ping"] = "ok" if ping_ok else "failed"
            if not ping_ok:
                ready = False
        else:
            details["db_ping"] = "no_client"
            ready = False
    except Exception:
        details["db_ping"] = "error"
        ready = False

    status_code = 200 if ready else 503
    return JSONResponse({"ready": ready, "details": details}, status_code=status_code)


# Optional Prometheus metrics endpoint
if SERVE_METRICS:
    @app.get("/metrics")
    async def metrics():
        resp = generate_latest()
        return PlainTextResponse(content=resp.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


# Request model adapter - simple validation for the expected fields
from pydantic import BaseModel

class ProcessRequest(BaseModel):
    thread_id: str
    user_id: Optional[str] = None
    text: str
    metadata: Optional[dict] = None


@app.post("/process")
async def process_endpoint(request: Request, payload: ProcessRequest):
    endpoint = "/process"
    method = "POST"
    REQUEST_COUNT.labels(endpoint=endpoint, method=method, status="started")
    with REQUEST_LATENCY.labels(endpoint=endpoint).time():
        dm: DialogueManager = app.state.dialogue_manager
        if dm is None:
            REQUEST_COUNT.labels(endpoint=endpoint, method=method, status="error").inc()
            raise HTTPException(status_code=503, detail="DialogueManager not ready")

        # Build internal UserMessage
        try:
            user_message = UserMessage(thread_id=payload.thread_id, user_id=payload.user_id, text=payload.text, metadata=payload.metadata)
        except Exception as e:
            REQUEST_COUNT.labels(endpoint=endpoint, method=method, status="bad_request").inc()
            raise HTTPException(status_code=400, detail=f"Invalid request payload: {e}")

        try:
            state: State = await dm.process(user_message)
            REQUEST_COUNT.labels(endpoint=endpoint, method=method, status="ok").inc()
            # Assume State has to_dict method
            return JSONResponse(state.to_dict())
        except DialogueManagerException as e:
            REQUEST_COUNT.labels(endpoint=endpoint, method=method, status="error").inc()
            logger.warning(f"Application-level error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            REQUEST_COUNT.labels(endpoint=endpoint, method=method, status="error").inc()
            logger.exception("Unhandled error while processing message")
            raise HTTPException(status_code=500, detail="Internal server error")


# Run via uvicorn main entrypoint
def run():
    # uvicorn will handle signals and ASGI lifespan by default
    uvicorn.run("__main__:app", host=APP_HOST, port=APP_PORT, log_level=LOG_LEVEL.lower(), workers=WORKERS)


if __name__ == "__main__":
    run()
