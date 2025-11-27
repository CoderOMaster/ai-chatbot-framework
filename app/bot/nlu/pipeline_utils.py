import os
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum

import httpx

from app.bot.nlu.pipeline import NLUPipeline
from app.bot.nlu.featurizers import SpacyFeaturizer
from app.bot.nlu.intent_classifiers import SklearnIntentClassifier
from app.bot.nlu.entity_extractors import CRFEntityExtractor
from app.bot.nlu.entity_extractors import SynonymReplacer
from app.bot.nlu.llm import ZeroShotNLUOpenAI
from app.config import app_config


class TrainingJobStatus(str, Enum):
    """Training job status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelRegistry:
    """Model registry for versioning and tracking trained models."""

    def __init__(self, registry_table_name: str = "nlu_model_registry"):
        """
        Initialize model registry.
        
        Args:
            registry_table_name: DynamoDB table name for model registry
        """
        self.registry_table_name = registry_table_name
        self.dynamodb = self._get_dynamodb_client()

    def _get_dynamodb_client(self):
        """Get DynamoDB client."""
        import boto3
        return boto3.resource("dynamodb")

    def register_model(
        self,
        model_id: str,
        version: str,
        pipeline_type: str,
        model_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Register a trained model in the registry.
        
        Args:
            model_id: Unique model identifier
            version: Model version
            pipeline_type: Type of pipeline (traditional/llm)
            model_path: Path to saved model
            metadata: Additional metadata
            
        Returns:
            Registry entry
        """
        table = self.dynamodb.Table(self.registry_table_name)
        entry = {
            "model_id": model_id,
            "version": version,
            "pipeline_type": pipeline_type,
            "model_path": model_path,
            "created_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }
        table.put_item(Item=entry)
        return entry

    def get_latest_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest version of a model.
        
        Args:
            model_id: Model identifier
            
        Returns:
            Latest model registry entry or None
        """
        table = self.dynamodb.Table(self.registry_table_name)
        response = table.query(
            KeyConditionExpression="model_id = :model_id",
            ExpressionAttributeValues={":model_id": model_id},
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None


class TrainingJobTracker:
    """Track training job progress and status."""

    def __init__(self, jobs_table_name: str = "nlu_training_jobs"):
        """
        Initialize training job tracker.
        
        Args:
            jobs_table_name: DynamoDB table name for job tracking
        """
        self.jobs_table_name = jobs_table_name
        self.dynamodb = self._get_dynamodb_client()

    def _get_dynamodb_client(self):
        """Get DynamoDB client."""
        import boto3
        return boto3.resource("dynamodb")

    def create_job(self, bot_id: str) -> str:
        """
        Create a new training job.
        
        Args:
            bot_id: Bot identifier
            
        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        table = self.dynamodb.Table(self.jobs_table_name)
        table.put_item(
            Item={
                "job_id": job_id,
                "bot_id": bot_id,
                "status": TrainingJobStatus.PENDING.value,
                "created_at": datetime.utcnow().isoformat(),
                "progress": 0,
                "error": None,
            }
        )
        return job_id

    def update_job_status(
        self,
        job_id: str,
        status: TrainingJobStatus,
        progress: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """
        Update training job status.
        
        Args:
            job_id: Job identifier
            status: New status
            progress: Progress percentage (0-100)
            error: Error message if failed
        """
        table = self.dynamodb.Table(self.jobs_table_name)
        update_expr = "SET #status = :status, progress = :progress, updated_at = :updated_at"
        expr_values = {
            ":status": status.value,
            ":progress": progress,
            ":updated_at": datetime.utcnow().isoformat(),
        }

        if error:
            update_expr += ", #error = :error"
            expr_values[":error"] = error

        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "error",
            },
            ExpressionAttributeValues=expr_values,
        )

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get training job status.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status or None
        """
        table = self.dynamodb.Table(self.jobs_table_name)
        response = table.get_item(Key={"job_id": job_id})
        return response.get("Item")


class PipelineAPIClient:
    """Client for calling internal pipeline APIs."""

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL for internal API calls
        """
        self.base_url = base_url or app_config.INTERNAL_API_URL

    async def list_intents(self, bot_id: str = "default") -> list:
        """
        Get list of intents via internal API.
        
        Args:
            bot_id: Bot identifier
            
        Returns:
            List of intents
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/admin/intents",
                params={"bot_id": bot_id},
            )
            response.raise_for_status()
            return response.json()

    async def list_synonyms(self, bot_id: str = "default") -> list:
        """
        Get list of synonyms via internal API.
        
        Args:
            bot_id: Bot identifier
            
        Returns:
            List of synonyms
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/admin/entities/synonyms",
                params={"bot_id": bot_id},
            )
            response.raise_for_status()
            return response.json()

    async def get_nlu_config(self, bot_id: str = "default") -> Dict[str, Any]:
        """
        Get NLU configuration via internal API.
        
        Args:
            bot_id: Bot identifier
            
        Returns:
            NLU configuration
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/admin/bots/{bot_id}/nlu-config",
            )
            response.raise_for_status()
            return response.json()


# Global instances
_api_client = PipelineAPIClient()
_model_registry = ModelRegistry()
_job_tracker = TrainingJobTracker()


async def get_pipeline(bot_id: str = "default") -> NLUPipeline:
    """
    Get NLU pipeline (Lambda-suitable, quick operation).
    
    Args:
        bot_id: Bot identifier
        
    Returns:
        Configured NLU pipeline
    """
    nlu_config = await _api_client.get_nlu_config(bot_id)
    
    if nlu_config.get("pipeline_type") == "traditional":
        return await create_ml_pipeline(
            bot_id=bot_id,
            **nlu_config.get("traditional_settings", {})
        )
    elif nlu_config.get("pipeline_type") == "llm":
        return await create_zero_shot_pipeline(
            bot_id=bot_id,
            **nlu_config.get("llm_settings", {})
        )
    else:
        raise ValueError(f"Unknown pipeline type: {nlu_config.get('pipeline_type')}")


async def create_ml_pipeline(bot_id: str = "default", **kwargs) -> NLUPipeline:
    """
    Create a machine learning pipeline.
    
    Args:
        bot_id: Bot identifier
        **kwargs: Additional pipeline configuration
        
    Returns:
        Configured ML pipeline
    """
    synonyms = await _api_client.list_synonyms(bot_id)
    return NLUPipeline(
        [
            SpacyFeaturizer(app_config.SPACY_LANG_MODEL),
            SklearnIntentClassifier(),
            CRFEntityExtractor(),
            SynonymReplacer(synonyms),
        ]
    )


async def create_zero_shot_pipeline(bot_id: str = "default", **kwargs) -> NLUPipeline:
    """
    Create a zero-shot LLM pipeline.
    
    Args:
        bot_id: Bot identifier
        **kwargs: Additional pipeline configuration
        
    Returns:
        Configured zero-shot pipeline
    """
    intents = await _api_client.list_intents(bot_id)
    synonyms = await _api_client.list_synonyms(bot_id)

    intent_ids = []
    entity_ids = []

    for intent in intents:
        intent_ids.append(intent.get("intentId"))
        for parameter in intent.get("parameters", []):
            entity_ids.append(parameter.get("name"))

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


async def enqueue_training_job(bot_id: str = "default") -> str:
    """
    Enqueue a training job for async processing (SQS/Celery).
    
    This function is Lambda-suitable and returns immediately with a job ID.
    The actual training is performed by an ECS Fargate task.
    
    Args:
        bot_id: Bot identifier
        
    Returns:
        Training job ID
    """
    job_id = _job_tracker.create_job(bot_id)
    
    # Send message to SQS queue for ECS Fargate task
    sqs_client = _get_sqs_client()
    queue_url = app_config.TRAINING_QUEUE_URL
    
    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=str({
            "job_id": job_id,
            "bot_id": bot_id,
            "action": "train_pipeline",
        }),
    )
    
    return job_id


def _get_sqs_client():
    """Get SQS client."""
    import boto3
    return boto3.client("sqs")


async def train_pipeline(bot_id: str = "default", job_id: Optional[str] = None) -> None:
    """
    Train NLU pipeline (long-running job, runs in ECS Fargate).
    
    This function should be invoked by an ECS Fargate task triggered by SQS.
    It updates job status in DynamoDB as it progresses.
    
    Args:
        bot_id: Bot identifier
        job_id: Training job ID for progress tracking
    """
    if not job_id:
        job_id = _job_tracker.create_job(bot_id)

    try:
        _job_tracker.update_job_status(job_id, TrainingJobStatus.IN_PROGRESS, progress=10)

        models_dir = app_config.MODELS_DIR
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)

        # Get training data
        _job_tracker.update_job_status(job_id, TrainingJobStatus.IN_PROGRESS, progress=20)
        intents = await _api_client.list_intents(bot_id)
        
        if not intents:
            raise Exception("No intents found for training")

        # Prepare training data
        _job_tracker.update_job_status(job_id, TrainingJobStatus.IN_PROGRESS, progress=40)
        training_data = []
        for intent in intents:
            for example in intent.get("trainingData", []):
                if example.get("text", "").strip() == "":
                    continue
                example["intent"] = intent.get("intentId")
                training_data.append(example)

        # Initialize and train pipeline
        _job_tracker.update_job_status(job_id, TrainingJobStatus.IN_PROGRESS, progress=60)
        pipeline = await get_pipeline(bot_id)
        
        _job_tracker.update_job_status(job_id, TrainingJobStatus.IN_PROGRESS, progress=80)
        pipeline.train(training_data, models_dir)

        # Register model
        _job_tracker.update_job_status(job_id, TrainingJobStatus.IN_PROGRESS, progress=90)
        model_version = datetime.utcnow().isoformat()
        nlu_config = await _api_client.get_nlu_config(bot_id)
        
        _model_registry.register_model(
            model_id=bot_id,
            version=model_version,
            pipeline_type=nlu_config.get("pipeline_type", "traditional"),
            model_path=models_dir,
            metadata={"job_id": job_id},
        )

        _job_tracker.update_job_status(job_id, TrainingJobStatus.COMPLETED, progress=100)

    except Exception as e:
        _job_tracker.update_job_status(
            job_id,
            TrainingJobStatus.FAILED,
            error=str(e),
        )
        raise


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get training job status (Lambda-suitable).
    
    Args:
        job_id: Training job ID
        
    Returns:
        Job status information
    """
    return _job_tracker.get_job_status(job_id)


def get_latest_model(bot_id: str) -> Optional[Dict[str, Any]]:
    """
    Get latest trained model metadata (Lambda-suitable).
    
    Args:
        bot_id: Bot identifier
        
    Returns:
        Latest model registry entry or None
    """
    return _model_registry.get_latest_model(bot_id)