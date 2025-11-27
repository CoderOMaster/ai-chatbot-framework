"""Training routes for Lambda-based CRUD and async job management."""
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
import httpx

from app.bot.nlu.pipeline_utils import (
    enqueue_training_job,
    get_job_status,
    TrainingJobStatus,
)
from app.config import app_config

router = APIRouter(prefix="/train", tags=["train"])


async def _call_intents_api(method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Any:
    """
    Call internal intents API via HTTP.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        endpoint: API endpoint path
        data: Request body data
        
    Returns:
        API response data
        
    Raises:
        HTTPException: If API call fails
    """
    base_url = app_config.INTERNAL_API_URL or "http://localhost:8000"
    url = f"{base_url}{endpoint}"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if method == "GET":
                response = await client.get(url)
            elif method == "POST":
                response = await client.post(url, json=data)
            elif method == "PUT":
                response = await client.put(url, json=data)
            elif method == "DELETE":
                response = await client.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Internal API error: {str(e)}")


@router.post("/{intent_id}/data")
async def save_training_data(intent_id: str, training_data: list[dict]) -> Dict[str, Any]:
    """
    Save training data for a given intent (Lambda-suitable, fast operation).
    
    Args:
        intent_id: Intent ID
        training_data: List of training examples
        
    Returns:
        Success response
        
    Raises:
        HTTPException: If intent not found or API call fails
    """
    # Verify intent exists via internal API
    try:
        intent = await _call_intents_api("GET", f"/admin/intents/{intent_id}")
    except HTTPException:
        raise HTTPException(status_code=404, detail="Intent not found")
    
    # Update intent with training data
    intent_update = intent.copy()
    intent_update["trainingData"] = training_data
    
    try:
        await _call_intents_api("PUT", f"/admin/intents/{intent_id}", intent_update)
    except HTTPException as e:
        raise HTTPException(status_code=500, detail=f"Failed to save training data: {str(e)}")
    
    return {"status": "success", "intent_id": intent_id, "data_count": len(training_data)}


@router.get("/{intent_id}/data")
async def get_training_data(intent_id: str) -> Dict[str, Any]:
    """
    Retrieve training data for a given intent (Lambda-suitable, fast operation).
    
    Args:
        intent_id: Intent ID
        
    Returns:
        Training data for the intent
        
    Raises:
        HTTPException: If intent not found or API call fails
    """
    try:
        intent = await _call_intents_api("GET", f"/admin/intents/{intent_id}")
    except HTTPException:
        raise HTTPException(status_code=404, detail="Intent not found")
    
    training_data = intent.get("trainingData", [])
    return {
        "intent_id": intent_id,
        "data": training_data,
        "count": len(training_data),
    }


@router.post("/build_models")
async def build_models(bot_id: str = Query(default="default")) -> Dict[str, Any]:
    """
    Trigger async training job for building Intent classification and NER models.
    
    This endpoint is Lambda-suitable and returns immediately with a job ID.
    The actual training is performed by an ECS Fargate task triggered via SQS.
    
    Args:
        bot_id: Bot identifier
        
    Returns:
        Job ID and status for tracking
    """
    try:
        job_id = await enqueue_training_job(bot_id)
        return {
            "status": "training_queued",
            "job_id": job_id,
            "bot_id": bot_id,
            "message": "Training job has been queued. Use /train/jobs/{job_id} to check status.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue training job: {str(e)}")


@router.get("/jobs/{job_id}")
async def get_training_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get training job status and progress (Lambda-suitable, fast operation).
    
    Args:
        job_id: Training job ID
        
    Returns:
        Job status, progress, and error details if applicable
        
    Raises:
        HTTPException: If job not found
    """
    job_status = get_job_status(job_id)
    
    if not job_status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return {
        "job_id": job_id,
        "status": job_status.get("status"),
        "progress": job_status.get("progress", 0),
        "bot_id": job_status.get("bot_id"),
        "created_at": job_status.get("created_at"),
        "updated_at": job_status.get("updated_at"),
        "error": job_status.get("error"),
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_training_job(job_id: str) -> Dict[str, Any]:
    """
    Cancel a training job (Lambda-suitable, fast operation).
    
    Only jobs in PENDING or IN_PROGRESS status can be cancelled.
    
    Args:
        job_id: Training job ID
        
    Returns:
        Cancellation status
        
    Raises:
        HTTPException: If job not found or cannot be cancelled
    """
    job_status = get_job_status(job_id)
    
    if not job_status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    current_status = job_status.get("status")
    
    if current_status == TrainingJobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a completed training job"
        )
    elif current_status == TrainingJobStatus.FAILED.value:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a failed training job"
        )
    
    # Note: Actual cancellation of ECS task should be handled by the training service
    # This endpoint marks the job as cancelled in the tracker
    try:
        from app.bot.nlu.pipeline_utils import _job_tracker
        _job_tracker.update_job_status(
            job_id,
            TrainingJobStatus.FAILED,
            error="Cancelled by user"
        )
        return {
            "status": "cancelled",
            "job_id": job_id,
            "message": "Training job has been cancelled",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")