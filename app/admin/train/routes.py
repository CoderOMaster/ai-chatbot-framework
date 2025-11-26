import json
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
import httpx
import boto3
from pydantic import BaseModel

router = APIRouter(prefix="/train", tags=["train"])

# AWS clients
sqs_client = boto3.client("sqs")
SQS_QUEUE_URL = "https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"


class TrainingJobRequest(BaseModel):
    """Request model for training job submission"""
    webhook_url: Optional[str] = None
    callback_url: Optional[str] = None


class TrainingJobResponse(BaseModel):
    """Response model for training job"""
    job_id: str
    status: str
    message: str


class TrainingJobStatus(BaseModel):
    """Training job status model"""
    job_id: str
    status: str  # pending, running, completed, failed
    progress: Optional[int] = None
    error: Optional[str] = None


# In-memory job tracking (replace with DynamoDB for production)
_job_store: dict[str, dict] = {}


@router.post("/{intent_id}/data")
async def save_training_data(intent_id: str, training_data: list[dict]):
    """
    Save training data for a given intent via admin-data service.
    
    Args:
        intent_id: The intent identifier
        training_data: List of training data samples
        
    Returns:
        Success status response
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://admin-data-service/intents/{intent_id}",
                timeout=10.0
            )
            response.raise_for_status()
            intent = response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=404, detail="Intent not found") from e

    # Update intent with training data
    try:
        async with httpx.AsyncClient() as client:
            await client.put(
                f"http://admin-data-service/intents/{intent_id}",
                json={"trainingData": training_data},
                timeout=10.0
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail="Failed to save training data") from e

    return {"status": "success"}


@router.get("/{intent_id}/data")
async def get_training_data(intent_id: str):
    """
    Retrieve training data for a given intent from admin-data service.
    
    Args:
        intent_id: The intent identifier
        
    Returns:
        Training data for the intent
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://admin-data-service/intents/{intent_id}",
                timeout=10.0
            )
            response.raise_for_status()
            intent = response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=404, detail="Intent not found") from e

    return intent.get("trainingData", [])


@router.post("/build_models", response_model=TrainingJobResponse)
async def build_models(request: TrainingJobRequest) -> TrainingJobResponse:
    """
    Submit a training job to NLU training service via SQS.
    
    This Lambda endpoint accepts training requests and submits them as async jobs
    to SQS for processing by the NLU training microservice.
    
    Args:
        request: Training job request with optional webhook/callback URLs
        
    Returns:
        Job ID and status
    """
    job_id = str(uuid.uuid4())
    
    # Prepare job message
    job_message = {
        "job_id": job_id,
        "action": "train_pipeline",
        "webhook_url": request.webhook_url,
        "callback_url": request.callback_url,
    }
    
    try:
        # Submit to SQS queue
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(job_message),
            MessageAttributes={
                "job_id": {"StringValue": job_id, "DataType": "String"},
                "action": {"StringValue": "train_pipeline", "DataType": "String"},
            }
        )
        
        # Track job status
        _job_store[job_id] = {
            "status": "pending",
            "progress": 0,
            "webhook_url": request.webhook_url,
        }
        
        return TrainingJobResponse(
            job_id=job_id,
            status="pending",
            message="Training job submitted successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit training job: {str(e)}"
        ) from e


@router.get("/jobs/{job_id}/status", response_model=TrainingJobStatus)
async def get_training_status(job_id: str) -> TrainingJobStatus:
    """
    Get the status of a training job.
    
    Args:
        job_id: The training job identifier
        
    Returns:
        Current job status, progress, and any errors
    """
    if job_id not in _job_store:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = _job_store[job_id]
    return TrainingJobStatus(
        job_id=job_id,
        status=job.get("status", "unknown"),
        progress=job.get("progress"),
        error=job.get("error"),
    )


@router.post("/jobs/{job_id}/webhook")
async def update_training_progress(job_id: str, status: str, progress: int = 0, error: Optional[str] = None):
    """
    Webhook endpoint for NLU training service to report progress.
    
    This endpoint is called by the NLU training microservice to update
    job status and progress. It also triggers callbacks to registered webhooks.
    
    Args:
        job_id: The training job identifier
        status: Current status (running, completed, failed)
        progress: Progress percentage (0-100)
        error: Error message if status is failed
    """
    if job_id not in _job_store:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = _job_store[job_id]
    job["status"] = status
    job["progress"] = progress
    if error:
        job["error"] = error
    
    # If job completed, trigger dialogue manager reload
    if status == "completed":
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://dialogue-manager-service/reload",
                    timeout=30.0
                )
        except httpx.HTTPError as e:
            # Log but don't fail - training completed successfully
            print(f"Warning: Failed to reload dialogue manager: {e}")
    
    # Trigger registered webhook if provided
    if job.get("webhook_url"):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    job["webhook_url"],
                    json={
                        "job_id": job_id,
                        "status": status,
                        "progress": progress,
                        "error": error,
                    },
                    timeout=10.0
                )
        except httpx.HTTPError as e:
            print(f"Warning: Failed to call webhook {job['webhook_url']}: {e}")
    
    return {"status": "progress updated"}