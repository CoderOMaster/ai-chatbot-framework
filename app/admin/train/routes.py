"""
Training API routes for asynchronous model training job submission.

This module provides HTTP endpoints for managing training data and submitting
long-running training jobs to a worker queue or Kubernetes Job. Training is
delegated to a separate microservice to avoid blocking the API process.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.admin.intents import store
from app.bot.nlu.pipeline_utils import train_pipeline
from app.common.job_queue import submit_training_job, TrainingJobConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/train", tags=["train"])


class TrainingDataRequest(BaseModel):
    """Request model for saving training data."""
    training_data: list[dict]


class TrainingJobResponse(BaseModel):
    """Response model for training job submission."""
    status: str
    job_id: str
    message: str


@router.post("/{intent_id}/data")
async def save_training_data(intent_id: str, request: TrainingDataRequest):
    """
    Save training data for a given intent.
    
    Args:
        intent_id: The intent ID to save training data for
        request: Request containing training data list
        
    Returns:
        dict: Status confirmation
        
    Raises:
        HTTPException: If intent not found
    """
    intent = await store.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    intent.trainingData = request.training_data
    await store.edit_intent(intent_id, intent.model_dump())
    return {"status": "success"}


@router.get("/{intent_id}/data")
async def get_training_data(intent_id: str):
    """
    Retrieve training data for a given intent.
    
    Args:
        intent_id: The intent ID to retrieve training data for
        
    Returns:
        dict: Training data for the intent
        
    Raises:
        HTTPException: If intent not found
    """
    intent = await store.get_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    return {"training_data": intent.trainingData}


@router.post("/build_models")
async def build_models(
    training_type: str = "traditional",
    bot_id: str = "default",
) -> TrainingJobResponse:
    """
    Submit a long-running training job to the worker queue.
    
    This endpoint enqueues training work to a separate microservice (e.g., Kubernetes Job,
    message queue worker) instead of running heavy training inside the API process.
    The training worker will:
    1. Read intents and entities from MongoDB
    2. Train the NLU pipeline
    3. Save models to MODELS_DIR
    4. Notify the dialogue-manager service to reload models
    
    Args:
        training_type: Type of pipeline to train ("traditional" or "llm")
        bot_id: Bot identifier for multi-bot support
        
    Returns:
        TrainingJobResponse: Job submission status with job_id
        
    Raises:
        HTTPException: If job submission fails
    """
    try:
        logger.info(
            f"Submitting training job: training_type={training_type}, bot_id={bot_id}"
        )
        
        # Create training job configuration
        job_config = TrainingJobConfig(
            training_type=training_type,
            bot_id=bot_id,
        )
        
        # Submit job to worker queue/Kubernetes
        job_id = await submit_training_job(job_config)
        
        logger.info(f"Training job submitted successfully: job_id={job_id}")
        
        return TrainingJobResponse(
            status="submitted",
            job_id=job_id,
            message="Training job enqueued. Check job status for progress.",
        )
    except Exception as e:
        logger.error(f"Failed to submit training job: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit training job: {str(e)}",
        )


@router.get("/jobs/{job_id}")
async def get_training_job_status(job_id: str) -> dict:
    """
    Get the status of a submitted training job.
    
    Args:
        job_id: The training job ID
        
    Returns:
        dict: Job status information
        
    Raises:
        HTTPException: If job not found
    """
    try:
        from app.common.job_queue import get_job_status
        
        status = await get_job_status(job_id)
        if not status:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return status
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job status: {str(e)}",
        )