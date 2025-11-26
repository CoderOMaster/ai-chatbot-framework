from typing import List
import os
import logging

import aiohttp
from fastapi import APIRouter, HTTPException, Depends

from app.admin.intents.store import IntentRepository

router = APIRouter(prefix="/train", tags=["train"])
logger = logging.getLogger(__name__)


@router.post("/{intent_id}/data")
async def save_training_data(
    intent_id: str, training_data: List[dict], intent_repo: IntentRepository = Depends()
):
    """Save training data for a given intent using an injected IntentRepository.

    The repository implementation must be provided by the application via
    FastAPI dependency injection (this keeps the route decoupled from any
    concrete storage implementation and makes it safe for split deployments).
    """
    intent = await intent_repo.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    intent.trainingData = training_data
    await intent_repo.edit_intent(intent_id, intent.model_dump())
    return {"status": "success"}


@router.get("/{intent_id}/data")
async def get_training_data(intent_id: str, intent_repo: IntentRepository = Depends()):
    """Retrieve training data for a given intent using an injected IntentRepository."""
    intent = await intent_repo.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    return intent.trainingData


@router.post("/build_models")
async def build_models() -> dict:
    """Enqueue a training job on the dedicated training-worker service.

    This endpoint no longer performs training in-process. Instead it sends a
    request to a configured training-worker (TRAINING_WORKER_URL) which is
    responsible for running train_pipeline and publishing resulting models to
    shared storage. The training worker should also notify or trigger the
    dialogue-manager service to pick up new models.
    """
    training_worker_url = os.getenv("TRAINING_WORKER_URL")
    if not training_worker_url:
        raise HTTPException(status_code=500, detail="Training worker URL not configured")

    endpoint = training_worker_url.rstrip("/") + "/jobs/train"
    payload = {
        "models_dir": os.getenv("MODELS_DIR", "/models"),
        "spacy_model": os.getenv("SPACY_MODEL", "en_core_web_sm"),
        "triggered_by": "admin_api",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error("Training worker responded %s: %s", resp.status, body)
                    raise HTTPException(status_code=502, detail="Training worker failed to enqueue job")
                # Prefer JSON response when available
                try:
                    data = await resp.json()
                except Exception:
                    data = {"status": "enqueued"}
    except aiohttp.ClientError as exc:
        logger.exception("Could not reach training worker at %s", training_worker_url)
        raise HTTPException(status_code=502, detail=str(exc))

    return {"status": "training_enqueued", "worker_response": data}