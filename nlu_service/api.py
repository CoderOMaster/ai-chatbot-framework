"""FastAPI application exposing a lightweight NLU inference API."""
from fastapi import FastAPI, HTTPException
import os
import logging
import asyncio
import psutil
from typing import Dict, Any

from nlu_service.pipeline import get_pipeline

logger = logging.getLogger("nlu_service")

app = FastAPI(title="nlu-runtime")

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
SPACY_LANG_MODEL = os.environ.get("SPACY_LANG_MODEL", "en_core_web_sm")

# health state
model_loaded = False
pipeline = None


async def load_models():
    global pipeline, model_loaded
    logger.info("Loading NLU models from %s", MODEL_DIR)
    try:
        pipeline = await get_pipeline()
        ok = pipeline.load(MODEL_DIR)
        model_loaded = bool(ok)
        logger.info("Model loaded: %s", model_loaded)
    except Exception as e:
        logger.exception("Failed to load models: %s", e)
        model_loaded = False


@app.on_event("startup")
async def startup_event():
    # load models in background to avoid blocking cold start too long
    loop = asyncio.get_event_loop()
    loop.create_task(load_models())


@app.get("/health")
async def health():
    mem = psutil.virtual_memory()
    if not model_loaded:
        raise HTTPException(status_code=503, detail="model not loaded")
    if mem.percent > 90:
        raise HTTPException(status_code=503, detail="memory pressure")
    return {"status": "ok", "model_loaded": model_loaded, "memory_percent": mem.percent}


@app.post("/predict")
async def predict_endpoint(payload: Dict[str, Any]):
    global pipeline
    if not model_loaded or pipeline is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    try:
        # pipeline.process is synchronous - run in threadpool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, pipeline.process, payload)
        return result
    except Exception as e:
        logger.exception("Error during prediction: %s", e)
        raise HTTPException(status_code=500, detail=str(e))