from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import psutil
import logging
from typing import Optional, Dict, Any
from app.bot.nlu.pipeline_utils import get_pipeline

logger = logging.getLogger("nlu_service")
app = FastAPI(title="NLU Runtime Service")

class PredictRequest(BaseModel):
    text: str

class PredictResponse(BaseModel):
    intent: Optional[Dict[str, Any]] = None
    intent_ranking: Optional[list] = None
    entities: Optional[Dict[str, Any]] = None

_pipeline = None
_model_loaded = False

@app.on_event("startup")
async def load_models():
    global _pipeline, _model_loaded
    try:
        _pipeline = await get_pipeline()
        # attempt load() from MODEL_DIR
        model_dir = os.environ.get("MODEL_DIR", "/models")
        _pipeline.load(model_dir)
        _model_loaded = True
        logger.info("model loaded", extra={"model_dir": model_dir})
    except Exception as e:
        logger.exception("failed to load models: %s", e)
        _model_loaded = False

@app.get("/health")
async def health() -> Dict[str, Any]:
    mem = psutil.virtual_memory()
    return {
        "ok": _model_loaded,
        "memory_percent": mem.percent,
    }

@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if not _pipeline:
        raise HTTPException(status_code=503, detail="model not ready")
    msg = {"text": req.text}
    out = _pipeline.process(msg)
    return PredictResponse(
        intent=out.get("intent"),
        intent_ranking=out.get("intent_ranking"),
        entities=out.get("entities"),
    )