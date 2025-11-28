from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.admin.intents.schemas import Intent
from app.admin.intents.store import IntentRepository, MongoIntentRepository
from app.bot.dialogue_manager.http_client import APICallException, call_api
from app.config import app_config
from app.database import create_collection_getter_from_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/train", tags=["train"])

_collection_getter = create_collection_getter_from_config(app_config)

_TRAINING_WORKER_SERVICE_URL = os.environ.get("TRAINING_WORKER_SERVICE_URL")
_TRAINING_WORKER_JOB_ENDPOINT = os.environ.get("TRAINING_WORKER_JOB_ENDPOINT", "/training/jobs")
DEFAULT_TRAINING_WORKER_TIMEOUT = 30.0


def _parse_training_worker_timeout(value: Optional[str], default: float = DEFAULT_TRAINING_WORKER_TIMEOUT) -> float:
    """Parse the configured training worker timeout into a float."""

    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(
            "Invalid TRAINING_WORKER_SERVICE_TIMEOUT=%s, falling back to %.1f seconds",
            value,
            default,
        )
        return default


_TRAINING_WORKER_SERVICE_TIMEOUT = _parse_training_worker_timeout(
    os.environ.get("TRAINING_WORKER_SERVICE_TIMEOUT")
)


class TrainingWorkerClient:
    """Client for enqueuing a training request with the background worker service."""

    def __init__(self, service_url: str, job_endpoint: str, timeout: float) -> None:
        self._service_url = service_url.rstrip("/")
        self._job_endpoint = job_endpoint
        self._timeout = timeout

    def _build_job_url(self) -> str:
        trimmed_endpoint = self._job_endpoint.lstrip("/")
        return f"{self._service_url}/{trimmed_endpoint}"

    async def enqueue_training_job(self, payload: Optional[dict[str, Any]] = None) -> None:
        """Request that the training worker begin building models."""

        await call_api(
            self._build_job_url(),
            "POST",
            headers={"Content-Type": "application/json"},
            parameters=payload or {},
            is_json=True,
            timeout=self._timeout,
        )


def get_intent_repository() -> IntentRepository:
    """Return an intent repository that can persist training data."""

    collection = _collection_getter("intents")
    return MongoIntentRepository(collection)


def get_training_worker_client() -> Optional[TrainingWorkerClient]:
    """Return a configured client or None if the worker service is not enabled."""

    if not _TRAINING_WORKER_SERVICE_URL:
        return None
    return TrainingWorkerClient(
        _TRAINING_WORKER_SERVICE_URL,
        _TRAINING_WORKER_JOB_ENDPOINT,
        _TRAINING_WORKER_SERVICE_TIMEOUT,
    )


@router.post("/{intent_id}/data")
async def save_training_data(
    intent_id: str,
    training_data: list[dict[str, Any]],
    repository: IntentRepository = Depends(get_intent_repository),
) -> dict[str, str]:
    """Persist the provided training examples on the requested intent."""

    intent: Intent | None = await repository.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Story not found")

    intent_payload = intent.model_dump()
    intent_payload["trainingData"] = training_data
    await repository.edit_intent(intent_id, intent_payload)
    return {"status": "success"}


@router.get("/{intent_id}/data")
async def get_training_data(
    intent_id: str,
    repository: IntentRepository = Depends(get_intent_repository),
) -> list[dict[str, Any]]:
    """Return the training data currently assigned to the requested intent."""

    intent: Intent | None = await repository.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Story not found")

    return intent.trainingData


@router.post("/build_models")
async def build_models(
    training_worker: Optional[TrainingWorkerClient] = Depends(get_training_worker_client),
) -> dict[str, str]:
    """Enqueue a training job with the dedicated worker service."""

    if training_worker is None:
        raise HTTPException(
            status_code=503,
            detail="Training worker service is not configured",
        )

    try:
        await training_worker.enqueue_training_job()
    except APICallException as exc:
        logger.error("Unable to enqueue training job: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Unable to schedule training job",
        ) from exc

    return {"status": "training job enqueued"}