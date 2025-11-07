import json
import logging
import os
import psutil
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ai_chatbot_common.config import get_settings
from app.bot.nlu.pipeline_utils import create_ml_pipeline, create_zero_shot_pipeline
from app.bot.nlu.pipeline import NLUPipeline

logger = logging.getLogger("nlu_service.runtime")

# Global pipeline instance
_PIPELINE: Optional[NLUPipeline] = None


class PredictRequest(BaseModel):
    text: str
    context: Dict[str, Any] = {}


class PredictResponse(BaseModel):
    intent: Dict[str, Any] | None = None
    entities: Dict[str, Any] | None = None


def _memory_ok(threshold_mb: int) -> bool:
    try:
        process = psutil.Process(os.getpid())
        rss_mb = process.memory_info().rss / (1024 * 1024)
        return rss_mb <= threshold_mb
    except Exception:
        return True


async def load_models_async() -> None:
    """Async model loader for use within an active event loop."""
    global _PIPELINE
    settings = get_settings()

    nlu_config = os.getenv("NLU_PIPELINE", "traditional")
    if nlu_config == "llm":
        pipeline = await create_zero_shot_pipeline()
    else:
        pipeline = await create_ml_pipeline()

    model_dir = settings.MODELS_DIR
    ok = pipeline.load(model_dir)
    if not ok:
        logger.info(
            json.dumps(
                {
                    "event": "nlu_model_load",
                    "status": "cold",
                    "model_dir": model_dir,
                    "spacy_model": settings.SPACY_LANG_MODEL,
                }
            )
        )
    else:
        logger.info(
            json.dumps(
                {
                    "event": "nlu_model_load",
                    "status": "warm",
                    "model_dir": model_dir,
                    "spacy_model": settings.SPACY_LANG_MODEL,
                }
            )
        )
    _PIPELINE = pipeline


def load_models() -> None:
    """Synchronous wrapper to load models outside an event loop (e.g., CLI)."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Should not be called in a running loop; prefer load_models_async
            raise RuntimeError("load_models() called while event loop is running")
        loop.run_until_complete(load_models_async())
    except RuntimeError:
        # Fall back to creating a new loop
        asyncio.run(load_models_async())


def predict(text: str) -> Dict[str, Any]:
    global _PIPELINE
    if _PIPELINE is None:
        raise RuntimeError("NLU pipeline not initialized; call load_models() first")
    result = _PIPELINE.process({"text": text})
    return {
        "intent": result.get("intent"),
        "entities": result.get("entities"),
    }


app = FastAPI()


@app.on_event("startup")
async def _startup():
    await load_models_async()


@app.get("/health")
async def health():
    if _PIPELINE is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    # Check memory threshold if provided
    threshold_mb = int(os.getenv("HEALTH_MAX_RSS_MB", "4096"))
    if not _memory_ok(threshold_mb):
        raise HTTPException(status_code=503, detail="memory high")
    return {"ok": True}


@app.post("/predict")
async def predict_api(req: PredictRequest) -> PredictResponse:
    try:
        out = predict(req.text)
        return PredictResponse(**out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))