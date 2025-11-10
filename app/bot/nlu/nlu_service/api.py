import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from app.bot.nlu.pipeline_utils import get_pipeline

logger = logging.getLogger("nlu_service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="NLU Runtime Service")

class PredictRequest(BaseModel):
    text: str
    context: Dict[str, Any] | None = None

class PredictResponse(BaseModel):
    intent: str | None = None
    entities: list[Dict[str, Any]] | None = None
    raw: Dict[str, Any] | None = None

STATE = {
    "loaded": False,
    "pipeline": None,
}

async def load_models():
    model_dir = os.getenv("MODEL_DIR", "/models")
    spacy_model = os.getenv("SPACY_LANG_MODEL", "xx_core_web_sm")
    logger.info("loading models", extra={"model_dir": model_dir, "spacy_lang_model": spacy_model})
    pipeline = await get_pipeline()
    # try load components from model dir; if fails, still keep pipeline
    try:
        pipeline.load(model_dir)
        logger.info("model loaded", extra={"model_dir": model_dir})
    except Exception as e:
        logger.warning("failed to load model, components may initialize lazily: %s", e)
    STATE["pipeline"] = pipeline
    STATE["loaded"] = True

@app.on_event("startup")
async def on_startup():
    await load_models()

@app.get("/health")
async def health():
    if not STATE["loaded"] or STATE["pipeline"] is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ok"}

@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if STATE["pipeline"] is None:
        raise HTTPException(status_code=503, detail="pipeline not ready")
    msg = {"text": req.text, "context": req.context or {}}
    result = STATE["pipeline"].process(msg)
    return PredictResponse(
        intent=result.get("intent"),
        entities=result.get("entities"),
        raw=result,
    )