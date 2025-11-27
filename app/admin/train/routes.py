import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Depends

from app.admin.intents.store import IntentRepository, parse_object_id, InvalidObjectId
from app.bot.nlu.pipeline_utils import train_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/train", tags=["train"])


def get_intent_repository(request: Request) -> IntentRepository:
    """Dependency to retrieve the IntentRepository from the application state.

    The application is expected to attach an IntentRepository instance to
    request.app.state.intent_repo during startup.
    """
    repo = getattr(request.app.state, "intent_repo", None)
    if repo is None:
        raise HTTPException(status_code=500, detail="Intent repository not configured")
    return repo


def validate_object_id(intent_id: str) -> str:
    """Validate that intent_id is a valid BSON ObjectId string.

    Returns the original intent_id when valid. Raises HTTPException(404)
    for invalid IDs so handlers don't need to repeat syntax checks.
    """
    try:
        parse_object_id(intent_id)
        return intent_id
    except InvalidObjectId:
        raise HTTPException(status_code=404, detail="Intent not found")


# Simple in-memory job queue and status store. This is intentionally lightweight
# and suitable for single-process deployments. A production deployment should
# replace this with a durable queue like Redis/RQ/Celery for resilience.
_JOB_QUEUE: Optional[asyncio.Queue] = None
_JOB_WORKER_TASK: Optional[asyncio.Task] = None
_JOB_STORE: Dict[str, Dict[str, Any]] = {}


def _ensure_queue_running() -> None:
    """Lazily create the queue and spawn a worker if not already running."""
    global _JOB_QUEUE, _JOB_WORKER_TASK
    if _JOB_QUEUE is None:
        _JOB_QUEUE = asyncio.Queue()
    if _JOB_WORKER_TASK is None or _JOB_WORKER_TASK.done():
        # create_task must be called from a running event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop; worker will be started when a request triggers enqueue
            return
        _JOB_WORKER_TASK = loop.create_task(_job_worker())


async def _job_worker() -> None:
    """Worker that consumes jobs from the in-memory queue and processes them."""
    global _JOB_QUEUE, _JOB_STORE
    logger.info("Job worker started")
    while True:
        job_id, bot_name = await _JOB_QUEUE.get()
        job = _JOB_STORE.get(job_id)
        if job is None:
            # unknown job - skip
            _JOB_QUEUE.task_done()
            continue
        job["status"] = "running"
        job["started_at"] = time.time()
        try:
            # Run the potentially long-running training pipeline
            await train_pipeline(bot_name=bot_name)
            job["status"] = "success"
        except Exception as e:
            logger.exception("Training job %s failed", job_id)
            job["status"] = "failed"
            job["error"] = str(e)
        finally:
            job["finished_at"] = time.time()
            # Attempt to reload dialogue manager if available but do not fail the job
            try:
                from app.dependencies.reload_dialogue_manager import reload_dialogue_manager

                try:
                    await reload_dialogue_manager()
                except Exception as e:
                    logger.warning("Reload dialogue manager raised: %s", e)
                    job.setdefault("warnings", []).append(f"reload_failed: {e}")
            except Exception:
                # The reload module may not exist in all deployments - non-fatal
                logger.debug("No reload_dialogue_manager available; skipping reload step")
            _JOB_QUEUE.task_done()


def _enqueue_training(bot_name: str = "default") -> str:
    """Create a new training job and place it onto the queue.

    Returns a job id which can be used to poll status.
    """
    global _JOB_QUEUE, _JOB_STORE
    job_id = uuid.uuid4().hex
    _JOB_STORE[job_id] = {"status": "queued", "created_at": time.time(), "bot": bot_name}
    _ensure_queue_running()
    # If queue is not running because there is no event loop, start a background
    # task via asyncio.create_task from the currently running loop when possible.
    if _JOB_QUEUE is not None:
        try:
            _JOB_QUEUE.put_nowait((job_id, bot_name))
        except Exception:
            # Fallback to synchronous put (shouldn't happen under normal async FastAPI)
            import asyncio as _asyncio

            loop = _asyncio.get_event_loop()
            loop.call_soon_threadsafe(lambda: _JOB_QUEUE.put_nowait((job_id, bot_name)))
    return job_id


@router.post("/{intent_id}/data")
async def save_training_data(
    intent_id: str,
    training_data: list[dict],
    repo: IntentRepository = Depends(get_intent_repository),
    validated_intent_id: str = Depends(validate_object_id),
):
    """Save training data for a given intent after validating the intent id.

    The IntentRepository is injected to ensure consistent database access.
    """
    # Confirm intent exists
    intent = await repo.get_intent(validated_intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    intent["trainingData"] = training_data
    await repo.edit_intent(validated_intent_id, intent)
    return {"status": "success"}


@router.get("/{intent_id}/data")
async def get_training_data(
    intent_id: str,
    repo: IntentRepository = Depends(get_intent_repository),
    validated_intent_id: str = Depends(validate_object_id),
):
    """Retrieve training data for a given intent."""
    intent = await repo.get_intent(validated_intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    return intent.get("trainingData", [])


@router.post("/build_models")
async def build_models(background_tasks: BackgroundTasks, bot_name: str = "default"):
    """Trigger asynchronous model training. Returns a job id to poll status.

    Training is enqueued to a lightweight in-memory queue to avoid blocking
    request handlers. For production, replace with a durable task queue.
    """
    job_id = _enqueue_training(bot_name=bot_name)
    # Ensure worker is started when running under FastAPI background tasks
    def _noop_start_worker():
        # This will call _ensure_queue_running in the request context / event loop
        _ensure_queue_running()

    background_tasks.add_task(_noop_start_worker)
    return {"status": "queued", "job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Return the status of a training job."""
    job = _JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # Return a minimal view of job status
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
        "warnings": job.get("warnings", []),
    }