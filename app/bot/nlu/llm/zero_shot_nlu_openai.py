import os
import sys
import time
import json
import signal
import logging
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from jinja2 import Environment, FileSystemLoader
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from app.bot.nlu.pipeline import NLUComponent

# Structured JSON logging setup
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": int(record.created * 1000),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger("zero_shot_nlu_service")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Prometheus metrics
REQUEST_COUNT = Counter(
    "nlu_requests_total",
    "Total number of NLU requests processed",
    ["method", "endpoint", "http_status"],
)
REQUEST_LATENCY = Histogram(
    "nlu_request_latency_seconds",
    "Latency of NLU request processing in seconds",
    ["endpoint"],
)

# Environment configuration
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "not-need-for-local-models")
OPENAI_MODEL_NAME = os.environ.get("OPENAI_MODEL_NAME", "not-need-for-local-models")
OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0"))
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "4096"))
PROMPTS_PATH = os.environ.get("PROMPTS_PATH", "app/bot/nlu/llm/prompts")
PROMPT_FILENAME = os.environ.get("PROMPT_FILENAME", "ZERO_SHOT_LEARNING_PROMPT.md")
SERVICE_PORT = int(os.environ.get("PORT", "8000"))
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))

# Database: create engine with pooling if DATABASE_URL provided
engine: Optional[Engine] = None
SessionLocal = None
if DATABASE_URL:
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_pre_ping=True,
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info(json.dumps({"event": "db_connected", "database_url": "****"}))
    except Exception as e:
        logger.error(json.dumps({"event": "db_connection_failed", "error": str(e)}))


class ZeroShotNLUOpenAI(NLUComponent):
    """
    Zero-shot NLU component using OpenAI compatible language model API to extract intents and entities.

    This class keeps the same logic as the original implementation but accepts configuration
    from environment variables and is suitable to be used within a microservice.
    """

    PROMPT_TEMPLATE_NAME = PROMPT_FILENAME

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        base_url: str = OPENAI_BASE_URL,
        api_key: str = OPENAI_API_KEY,
        model_name: str = OPENAI_MODEL_NAME,
        temperature: float = OPENAI_TEMPERATURE,
        max_tokens: int = OPENAI_MAX_TOKENS,
        prompts_path: str = PROMPTS_PATH,
    ):
        self.intents = intents or []
        self.entities = entities or []

        # Initialize the OpenAI LLM
        try:
            self.llm = ChatOpenAI(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
                extra_body={"max_tokens": max_tokens},
            )
        except Exception as e:
            logger.error(json.dumps({"event": "llm_init_failed", "error": str(e)}))
            raise

        # Load and render the prompt template
        try:
            env = Environment(loader=FileSystemLoader(prompts_path))
            template = env.get_template(self.PROMPT_TEMPLATE_NAME)
            system_prompt = template.render({"intents": self.intents, "entities": self.entities})
        except Exception as e:
            logger.error(json.dumps({"event": "prompt_load_failed", "path": prompts_path, "error": str(e)}))
            raise

        # Define the prompt template
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{text}"),
        ])

        # Define the processing chain
        self.chain = prompt_template | self.llm | JsonOutputParser()

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        # Zero-shot component: no training
        pass

    def load(self, model_path: str) -> bool:
        # Zero-shot component: nothing to load
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not message.get("text"):
            logger.warning(json.dumps({"event": "no_text", "message": message}))
            return message

        try:
            result = self.chain.invoke({"text": message.get("text")})

            # Extract intent
            intent_value = result.get("intent")
            if intent_value:
                intent = {"intent": intent_value, "confidence": 1.0}
                message["intent"] = intent
                message["intent_ranking"] = [intent]
            else:
                message["intent"] = {"intent": None, "confidence": 0.0}

            # Extract and filter entities
            entities = result.get("entities", {}) or {}
            message["entities"] = {k: v for k, v in entities.items() if v is not None}

        except Exception as e:
            logger.error(json.dumps({"event": "processing_error", "error": str(e)}))
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            message["entities"] = {}

        return message


# FastAPI application
app = FastAPI(title="ZeroShot NLU Service")

# Add CORS if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus ASGI app at /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Simple middleware to instrument requests
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency = time.time() - start_time
            endpoint = request.url.path
            REQUEST_LATENCY.labels(endpoint=endpoint).observe(latency)
            REQUEST_COUNT.labels(request.method, endpoint, str(status_code)).inc()

app.add_middleware(MetricsMiddleware)

# Service state
service_start_time = time.time()
component: Optional[ZeroShotNLUOpenAI] = None
is_ready = False


@app.on_event("startup")
def startup_event():
    global component, is_ready
    logger.info(json.dumps({"event": "startup", "port": SERVICE_PORT}))
    try:
        # Load intents/entities from env if provided (comma-separated)
        intents_env = os.environ.get("INTENTS", "")
        entities_env = os.environ.get("ENTITIES", "")
        intents = [i.strip() for i in intents_env.split(",") if i.strip()] if intents_env else []
        entities = [e.strip() for e in entities_env.split(",") if e.strip()] if entities_env else []

        component = ZeroShotNLUOpenAI(
            intents=intents,
            entities=entities,
            base_url=OPENAI_BASE_URL,
            api_key=OPENAI_API_KEY,
            model_name=OPENAI_MODEL_NAME,
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            prompts_path=PROMPTS_PATH,
        )

        # Optionally check DB connectivity
        if engine:
            try:
                conn = engine.connect()
                conn.close()
                logger.info(json.dumps({"event": "db_ping_success"}))
            except Exception as e:
                logger.error(json.dumps({"event": "db_ping_failed", "error": str(e)}))

        is_ready = True
        logger.info(json.dumps({"event": "service_ready"}))
    except Exception as e:
        logger.error(json.dumps({"event": "startup_failed", "error": str(e)}))
        is_ready = False


@app.on_event("shutdown")
def shutdown_event():
    global is_ready
    logger.info(json.dumps({"event": "shutdown"}))
    is_ready = False
    # Close DB engine if present
    try:
        if engine:
            engine.dispose()
            logger.info(json.dumps({"event": "db_engine_disposed"}))
    except Exception as e:
        logger.error(json.dumps({"event": "db_engine_dispose_failed", "error": str(e)}))


# Graceful SIGTERM handling
def _handle_sigterm(signum, frame):
    logger.info(json.dumps({"event": "sigterm_received", "signal": signum}))
    # FastAPI/uvicorn will call shutdown events; we log and exit
    try:
        sys.exit(0)
    except SystemExit:
        os._exit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)


@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "uptime_seconds": int(time.time() - service_start_time),
    })


@app.get("/readiness")
def readiness():
    return JSONResponse({"ready": bool(is_ready)})


@app.post("/process")
def process_message(payload: Dict[str, Any]):
    if not component:
        logger.error(json.dumps({"event": "not_initialized"}))
        raise HTTPException(status_code=503, detail="Service not initialized")

    message = payload if isinstance(payload, dict) else {"text": str(payload)}
    start = time.time()
    try:
        result = component.process(message)
        elapsed = time.time() - start
        logger.info(json.dumps({"event": "process_complete", "latency": elapsed}))
        return JSONResponse(result)
    except Exception as e:
        logger.error(json.dumps({"event": "process_failed", "error": str(e)}))
        raise HTTPException(status_code=500, detail=str(e))


# Optional: endpoint to fetch service info
@app.get("/info")
def info():
    return {
        "service": "zero_shot_nlu",
        "version": os.environ.get("SERVICE_VERSION", "0.1.0"),
        "llm_base_url": OPENAI_BASE_URL,
        "ready": is_ready,
    }


# If run as main, start uvicorn
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("__main__:app", host="0.0.0.0", port=SERVICE_PORT, log_level="info")
