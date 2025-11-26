"""
Job queue abstraction for asynchronous training job submission.

This module provides a pluggable interface for submitting long-running training
jobs to various backends (Kubernetes Jobs, message queues, etc.). It abstracts
the job submission and status tracking logic from the API layer.
"""

import logging
import uuid
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
from enum import Enum
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Training job status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingJobConfig(BaseModel):
    """Configuration for a training job."""
    training_type: str = "traditional"
    bot_id: str = "default"
    models_dir: Optional[str] = None


class JobInfo(BaseModel):
    """Information about a submitted job."""
    job_id: str
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    config: TrainingJobConfig


class JobQueueProvider(ABC):
    """
    Abstract base class for job queue providers.
    
    Defines the interface for submitting and tracking training jobs.
    Implementations can use Kubernetes Jobs, Celery, RQ, or other backends.
    """

    @abstractmethod
    async def submit_job(self, config: TrainingJobConfig) -> str:
        """
        Submit a training job to the queue.
        
        Args:
            config: Training job configuration
            
        Returns:
            str: Job ID for tracking
        """
        pass

    @abstractmethod
    async def get_status(self, job_id: str) -> Optional[JobInfo]:
        """
        Get the status of a submitted job.
        
        Args:
            job_id: The job ID
            
        Returns:
            JobInfo: Job information, or None if not found
        """
        pass


class InMemoryJobQueue(JobQueueProvider):
    """
    In-memory job queue provider for development/testing.
    
    Stores job information in memory. Not suitable for production.
    In production, use KubernetesJobQueue or a message queue backend.
    """

    def __init__(self):
        """Initialize the in-memory job store."""
        self._jobs: Dict[str, JobInfo] = {}

    async def submit_job(self, config: TrainingJobConfig) -> str:
        """
        Submit a job to the in-memory queue.
        
        Args:
            config: Training job configuration
            
        Returns:
            str: Generated job ID
        """
        job_id = str(uuid.uuid4())
        job_info = JobInfo(
            job_id=job_id,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            config=config,
        )
        self._jobs[job_id] = job_info
        logger.info(f"In-memory job submitted: {job_id}")
        return job_id

    async def get_status(self, job_id: str) -> Optional[JobInfo]:
        """
        Get job status from in-memory store.
        
        Args:
            job_id: The job ID
            
        Returns:
            JobInfo: Job information, or None if not found
        """
        return self._jobs.get(job_id)


class KubernetesJobQueue(JobQueueProvider):
    """
    Kubernetes Job queue provider for production deployments.
    
    Submits training jobs as Kubernetes Jobs and tracks their status
    via the Kubernetes API.
    """

    def __init__(self, namespace: str = "default", image: str = "nlu-training-worker:latest"):
        """
        Initialize the Kubernetes job queue provider.
        
        Args:
            namespace: Kubernetes namespace for training jobs
            image: Docker image for training worker pods
        """
        self.namespace = namespace
        self.image = image
        logger.info(f"Initialized KubernetesJobQueue: namespace={namespace}, image={image}")

    async def submit_job(self, config: TrainingJobConfig) -> str:
        """
        Submit a training job as a Kubernetes Job.
        
        Args:
            config: Training job configuration
            
        Returns:
            str: Kubernetes Job name (used as job ID)
        """
        try:
            from kubernetes import client, config as k8s_config
            
            # Load Kubernetes config
            k8s_config.load_incluster_config()
            
            job_id = f"training-{uuid.uuid4().hex[:8]}"
            
            # Create Kubernetes Job manifest
            job_manifest = self._create_job_manifest(job_id, config)
            
            # Submit job to Kubernetes
            v1 = client.BatchV1Api()
            v1.create_namespaced_job(
                namespace=self.namespace,
                body=job_manifest,
            )
            
            logger.info(f"Kubernetes job submitted: {job_id}")
            return job_id
        except Exception as e:
            logger.error(f"Failed to submit Kubernetes job: {str(e)}", exc_info=True)
            raise

    async def get_status(self, job_id: str) -> Optional[JobInfo]:
        """
        Get the status of a Kubernetes Job.
        
        Args:
            job_id: The Kubernetes Job name
            
        Returns:
            JobInfo: Job information, or None if not found
        """
        try:
            from kubernetes import client, config as k8s_config
            
            k8s_config.load_incluster_config()
            v1 = client.BatchV1Api()
            
            job = v1.read_namespaced_job(name=job_id, namespace=self.namespace)
            
            # Map Kubernetes job status to our JobStatus enum
            if job.status.succeeded:
                status = JobStatus.COMPLETED
            elif job.status.failed:
                status = JobStatus.FAILED
            elif job.status.active:
                status = JobStatus.RUNNING
            else:
                status = JobStatus.PENDING
            
            job_info = JobInfo(
                job_id=job_id,
                status=status,
                created_at=job.metadata.creation_timestamp,
                config=TrainingJobConfig(),  # Placeholder
            )
            
            return job_info
        except Exception as e:
            logger.warning(f"Failed to get Kubernetes job status: {str(e)}")
            return None

    def _create_job_manifest(self, job_id: str, config: TrainingJobConfig) -> Dict[str, Any]:
        """
        Create a Kubernetes Job manifest for training.
        
        Args:
            job_id: The job ID
            config: Training job configuration
            
        Returns:
            dict: Kubernetes Job manifest
        """
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_id,
                "namespace": self.namespace,
            },
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "training-worker",
                                "image": self.image,
                                "command": [
                                    "python",
                                    "-m",
                                    "app.bot.nlu.pipeline_utils",
                                    "train",
                                    "--training-type",
                                    config.training_type,
                                    "--bot-id",
                                    config.bot_id,
                                ],
                                "env": [
                                    {
                                        "name": "MODELS_DIR",
                                        "value": config.models_dir or "/models",
                                    },
                                ],
                            }
                        ],
                        "restartPolicy": "Never",
                    }
                },
                "backoffLimit": 3,
            },
        }


# Global job queue provider instance
_provider: Optional[JobQueueProvider] = None


def _get_provider() -> JobQueueProvider:
    """
    Get the global job queue provider.
    
    Lazily initializes the provider based on environment configuration.
    For development, uses InMemoryJobQueue.
    For production, uses KubernetesJobQueue.
    
    Returns:
        JobQueueProvider: The configured provider instance
    """
    global _provider
    if _provider is None:
        from app.common.config import get_settings
        
        settings = get_settings()
        
        # Check for Kubernetes configuration
        if getattr(settings, "KUBERNETES_ENABLED", False):
            namespace = getattr(settings, "KUBERNETES_NAMESPACE", "default")
            image = getattr(settings, "TRAINING_WORKER_IMAGE", "nlu-training-worker:latest")
            _provider = KubernetesJobQueue(namespace=namespace, image=image)
            logger.info("Using Kubernetes job queue provider")
        else:
            _provider = InMemoryJobQueue()
            logger.info("Using in-memory job queue provider (development mode)")
    
    return _provider


async def submit_training_job(config: TrainingJobConfig) -> str:
    """
    Submit a training job to the configured queue.
    
    This is the primary interface for submitting training jobs from the API layer.
    
    Args:
        config: Training job configuration
        
    Returns:
        str: Job ID for tracking
    """
    provider = _get_provider()
    return await provider.submit_job(config)


async def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the status of a submitted training job.
    
    Args:
        job_id: The job ID
        
    Returns:
        dict: Job status information, or None if not found
    """
    provider = _get_provider()
    job_info = await provider.get_status(job_id)
    
    if job_info is None:
        return None
    
    return {
        "job_id": job_info.job_id,
        "status": job_info.status.value,
        "created_at": job_info.created_at.isoformat(),
        "started_at": job_info.started_at.isoformat() if job_info.started_at else None,
        "completed_at": job_info.completed_at.isoformat() if job_info.completed_at else None,
        "error": job_info.error,
    }


def set_provider(provider: JobQueueProvider) -> None:
    """
    Set a custom job queue provider.
    
    Useful for testing or custom deployment scenarios.
    
    Args:
        provider: JobQueueProvider instance to use
    """
    global _provider
    _provider = provider
    logger.info(f"Set custom job queue provider: {type(provider).__name__}")