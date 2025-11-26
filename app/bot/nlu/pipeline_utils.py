"""
NLU Pipeline utilities for training and factory creation.

This module provides async job handlers for NLU pipeline training and factory methods
for creating both ML and LLM-based NLU pipelines with model versioning support.
"""

import os
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from uuid import uuid4

from shared.config import app_config
from shared.nlu.pipeline import NLUPipeline
from app.bot.nlu.featurizers import SpacyFeaturizer
from app.bot.nlu.intent_classifiers import SklearnIntentClassifier
from app.bot.nlu.entity_extractors import CRFEntityExtractor
from app.bot.nlu.entity_extractors import SynonymReplacer
from app.bot.nlu.llm import ZeroShotNLUOpenAI


class TrainingJobHandler:
    """Manages async NLU pipeline training jobs with progress tracking."""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}

    def create_job(self) -> str:
        """Create a new training job and return job ID."""
        job_id = str(uuid4())
        self.jobs[job_id] = {
            "status": "pending",
            "progress": 0,
            "created_at": datetime.utcnow(),
            "started_at": None,
            "completed_at": None,
            "error": None,
            "model_version": None,
        }
        return job_id

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a training job."""
        return self.jobs.get(job_id)

    def update_job_progress(self, job_id: str, progress: int, status: str = "running") -> None:
        """Update job progress and status."""
        if job_id in self.jobs:
            self.jobs[job_id]["progress"] = progress
            self.jobs[job_id]["status"] = status
            if status == "running" and not self.jobs[job_id]["started_at"]:
                self.jobs[job_id]["started_at"] = datetime.utcnow()

    def complete_job(self, job_id: str, model_version: str) -> None:
        """Mark job as completed with model version."""
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "completed"
            self.jobs[job_id]["progress"] = 100
            self.jobs[job_id]["completed_at"] = datetime.utcnow()
            self.jobs[job_id]["model_version"] = model_version

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark job as failed with error message."""
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "failed"
            self.jobs[job_id]["error"] = error
            self.jobs[job_id]["completed_at"] = datetime.utcnow()


# Global training job handler
_training_handler = TrainingJobHandler()


async def train_pipeline(
    job_id: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    webhook_url: Optional[str] = None,
) -> str:
    """
    Async job handler for NLU pipeline training.

    Args:
        job_id: Unique identifier for this training job
        progress_callback: Optional callback function for progress updates (progress, status)
        webhook_url: Optional webhook URL to notify on completion

    Returns:
        Model version identifier

    Raises:
        Exception: If no intents found or training fails
    """
    try:
        _training_handler.update_job_progress(job_id, 10, "initializing")
        if progress_callback:
            progress_callback(10, "initializing")

        models_dir = app_config.MODELS_DIR

        if not os.path.exists(models_dir):
            os.makedirs(models_dir)

        # Get all intents via service call
        _training_handler.update_job_progress(job_id, 20, "loading_intents")
        if progress_callback:
            progress_callback(20, "loading_intents")

        intents = await _get_intents_service()
        if not intents:
            raise Exception("No intents found for training")

        # Prepare training data
        _training_handler.update_job_progress(job_id, 30, "preparing_data")
        if progress_callback:
            progress_callback(30, "preparing_data")

        training_data = []
        for intent in intents:
            for example in intent.trainingData:
                if example.get("text", "").strip() == "":
                    continue
                example["intent"] = intent.intentId
                training_data.append(example)

        # Initialize and train pipeline
        _training_handler.update_job_progress(job_id, 50, "training")
        if progress_callback:
            progress_callback(50, "training")

        pipeline = await get_pipeline()
        pipeline.train(training_data, models_dir)

        # Generate model version
        model_version = f"v{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        _training_handler.complete_job(job_id, model_version)

        _training_handler.update_job_progress(job_id, 100, "completed")
        if progress_callback:
            progress_callback(100, "completed")

        # TODO: Call webhook_url if provided
        return model_version

    except Exception as e:
        error_msg = str(e)
        _training_handler.fail_job(job_id, error_msg)
        if progress_callback:
            progress_callback(0, f"failed: {error_msg}")
        raise


async def get_pipeline() -> NLUPipeline:
    """
    Factory method to create NLU pipeline based on configuration.

    Supports both ML and LLM modes with automatic selection based on
    NLU configuration.

    Returns:
        Configured NLUPipeline instance

    Raises:
        ValueError: If pipeline type is not supported
    """
    nlu_config = await _get_nlu_config_service()

    if nlu_config.pipeline_type == "traditional":
        return await create_ml_pipeline(**nlu_config.traditional_settings.dict())
    elif nlu_config.pipeline_type == "llm":
        return await create_zero_shot_pipeline(**nlu_config.llm_settings.dict())
    else:
        raise ValueError(f"Unsupported pipeline type: {nlu_config.pipeline_type}")


async def create_ml_pipeline(**kwargs) -> NLUPipeline:
    """
    Create a machine learning-based NLU pipeline.

    Combines Spacy featurization, Sklearn intent classification, CRF entity
    extraction, and synonym replacement.

    Args:
        **kwargs: Additional configuration parameters

    Returns:
        Configured NLUPipeline with ML components
    """
    synonyms = await _get_synonyms_service()
    return NLUPipeline(
        [
            SpacyFeaturizer(app_config.SPACY_LANG_MODEL),
            SklearnIntentClassifier(),
            CRFEntityExtractor(),
            SynonymReplacer(synonyms),
        ]
    )


async def create_zero_shot_pipeline(**kwargs) -> NLUPipeline:
    """
    Create a zero-shot LLM-based NLU pipeline.

    Uses OpenAI's zero-shot capabilities for intent classification and entity
    extraction without requiring training data.

    Args:
        **kwargs: Additional configuration parameters for LLM

    Returns:
        Configured NLUPipeline with LLM components
    """
    intents = await _get_intents_service()
    synonyms = await _get_synonyms_service()

    intent_ids = []
    entity_ids = []

    for intent in intents:
        intent_ids.append(intent.intentId)
        for parameter in intent.parameters:
            entity_ids.append(parameter.name)

    return NLUPipeline(
        [
            ZeroShotNLUOpenAI(
                intents=intent_ids,
                entities=entity_ids,
                **kwargs,
            ),
            SynonymReplacer(synonyms),
        ]
    )


# Service call wrappers (to be implemented with actual service layer)
async def _get_intents_service():
    """
    Fetch intents from admin service.

    This is a placeholder for service layer integration.
    Should be replaced with actual service call.
    """
    # TODO: Implement service call to admin.intents service
    from app.admin.intents.store import list_intents
    return await list_intents()


async def _get_synonyms_service():
    """
    Fetch synonyms from admin service.

    This is a placeholder for service layer integration.
    Should be replaced with actual service call.
    """
    # TODO: Implement service call to admin.entities service
    from app.admin.entities.store import list_synonyms
    return await list_synonyms()


async def _get_nlu_config_service(bot_id: str = "default"):
    """
    Fetch NLU configuration from admin service.

    This is a placeholder for service layer integration.
    Should be replaced with actual service call.

    Args:
        bot_id: Bot identifier (default: "default")
    """
    # TODO: Implement service call to admin.bots service
    from app.admin.bots.store import get_nlu_config
    return await get_nlu_config(bot_id)