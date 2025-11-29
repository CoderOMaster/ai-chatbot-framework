import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.admin.intents.schemas import Intent
from app.admin.train import routes
from app.bot.dialogue_manager.http_client import APICallException


@pytest.fixture
def sample_intent() -> Intent:
    """Create a representative intent used across multiple training endpoint tests."""

    return Intent(
        id=ObjectId(),
        name="story intent",
        userDefined=True,
        intentId="test-story",
        apiTrigger=False,
        speechResponse="ok",
        parameters=[],
        labeledSentences=[],
        trainingData=[{"text": "existing example"}],
    )


@pytest.fixture
def training_examples() -> list[dict[str, Any]]:
    """Return a minimal training example payload for persistence tests."""

    return [{"text": "new example"}]


@pytest.mark.asyncio
async def test_save_training_data_persists_examples(sample_intent: Intent, training_examples: list[dict[str, Any]]) -> None:
    """Ensure the save_training_data endpoint replaces the training examples for an intent."""

    repository = AsyncMock()
    repository.get_intent = AsyncMock(return_value=sample_intent)
    repository.edit_intent = AsyncMock()

    response = await routes.save_training_data(
        sample_intent.intentId,
        training_examples,
        repository=repository,
    )

    assert response == {"status": "success"}
    repository.get_intent.assert_awaited_once_with(sample_intent.intentId)
    repository.edit_intent.assert_awaited_once()

    repo_call_args, _ = repository.edit_intent.call_args
    assert repo_call_args[0] == sample_intent.intentId
    assert repo_call_args[1]["trainingData"] == training_examples


@pytest.mark.asyncio
async def test_save_training_data_missing_intent_raises_not_found() -> None:
    """Verify save_training_data raises when the requested intent cannot be found."""

    repository = AsyncMock()
    repository.get_intent = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as excinfo:
        await routes.save_training_data("missing-intent", [{"text": "ignored"}], repository=repository)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Story not found"


@pytest.mark.asyncio
async def test_get_training_data_returns_examples(sample_intent: Intent) -> None:
    """Ensure the get_training_data endpoint returns the stored training payload."""

    repository = AsyncMock()
    repository.get_intent = AsyncMock(return_value=sample_intent)

    training_data = await routes.get_training_data(sample_intent.intentId, repository=repository)

    assert training_data == sample_intent.trainingData
    repository.get_intent.assert_awaited_once_with(sample_intent.intentId)


@pytest.mark.asyncio
async def test_get_training_data_missing_intent_raises_not_found() -> None:
    """Verify get_training_data raises when the intent is absent from the store."""

    repository = AsyncMock()
    repository.get_intent = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as excinfo:
        await routes.get_training_data("missing", repository=repository)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Story not found"


@pytest.fixture
def dummy_training_worker() -> AsyncMock:
    """Provide a simple worker client mock that can be reused across build_models tests."""

    worker = AsyncMock()
    worker.enqueue_training_job = AsyncMock()
    return worker


@pytest.mark.asyncio
async def test_build_models_enqueue_job_success(dummy_training_worker: AsyncMock) -> None:
    """Ensure build_models enqueues a job and reports success when the worker is available."""

    result = await routes.build_models(training_worker=dummy_training_worker)

    assert result == {"status": "training job enqueued"}
    dummy_training_worker.enqueue_training_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_models_without_worker_raises_service_unavailable() -> None:
    """Verify build_models returns a 503 when the training worker service is disabled."""

    with pytest.raises(HTTPException) as excinfo:
        await routes.build_models(training_worker=None)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Training worker service is not configured"


@pytest.mark.asyncio
async def test_build_models_handles_worker_api_failure() -> None:
    """Ensure build_models surfaces a 502 when the worker client fails to enqueue."""

    worker = AsyncMock()
    worker.enqueue_training_job = AsyncMock(side_effect=APICallException("failed"))

    with pytest.raises(HTTPException) as excinfo:
        await routes.build_models(training_worker=worker)

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail == "Unable to schedule training job"
    worker.enqueue_training_job.assert_awaited_once()


def test_parse_training_worker_timeout_defaults_to_configured_default() -> None:
    """Confirm the timeout parser returns defaults when no value is provided."""

    assert routes._parse_training_worker_timeout(None, default=12.5) == 12.5


def test_parse_training_worker_timeout_parses_valid_value() -> None:
    """Ensure the parser converts numeric strings into floats."""

    assert routes._parse_training_worker_timeout("7.3") == 7.3


def test_parse_training_worker_timeout_warns_and_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    """Invalid numeric values should log a warning and fall back to the default."""

    caplog.set_level(logging.WARNING)
    timeout_value = routes._parse_training_worker_timeout("not-a-number", default=3.0)

    assert timeout_value == 3.0
    assert "Invalid TRAINING_WORKER_SERVICE_TIMEOUT" in caplog.text


def test_training_worker_client_build_job_url_trims_slashes() -> None:
    """The worker client should produce a well-formed URL regardless of trailing slashes."""

    client = routes.TrainingWorkerClient("https://worker/", "/jobs/run", 8.0)

    assert client._build_job_url() == "https://worker/jobs/run"


@pytest.mark.asyncio
async def test_training_worker_client_enqueue_calls_call_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify enqueue_training_job delegates to call_api with the expected parameters."""

    mock_call_api = AsyncMock()
    monkeypatch.setattr(routes, "call_api", mock_call_api)

    client = routes.TrainingWorkerClient("https://worker", "jobs", 5.5)
    payload = {"trigger": True}

    await client.enqueue_training_job(payload)

    mock_call_api.assert_awaited_once_with(
        "https://worker/jobs",
        "POST",
        headers={"Content-Type": "application/json"},
        parameters=payload,
        is_json=True,
        timeout=5.5,
    )


@pytest.mark.asyncio
async def test_training_worker_client_enqueue_without_payload_uses_empty_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty payload should be serialized to an empty parameter dictionary."""

    mock_call_api = AsyncMock()
    monkeypatch.setattr(routes, "call_api", mock_call_api)

    client = routes.TrainingWorkerClient("https://worker", "jobs", 2.0)

    await client.enqueue_training_job()

    mock_call_api.assert_awaited_once()
    _, kwargs = mock_call_api.call_args
    assert kwargs["parameters"] == {}


def test_get_training_worker_client_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the service URL is not configured, the dependency should return None."""

    monkeypatch.setattr(routes, "_TRAINING_WORKER_SERVICE_URL", None)

    assert routes.get_training_worker_client() is None


def test_get_training_worker_client_returns_client_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """An enabled worker configuration should yield a TrainingWorkerClient instance."""

    monkeypatch.setattr(routes, "_TRAINING_WORKER_SERVICE_URL", "https://worker")
    monkeypatch.setattr(routes, "_TRAINING_WORKER_JOB_ENDPOINT", "/jobs")
    monkeypatch.setattr(routes, "_TRAINING_WORKER_SERVICE_TIMEOUT", 11.0)

    client = routes.get_training_worker_client()

    assert isinstance(client, routes.TrainingWorkerClient)
    assert client._service_url == "https://worker"
    assert client._timeout == 11.0


def test_get_intent_repository_uses_collection_getter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The intent repository dependency should obtain the intents collection from the config getter."""

    sentinel_collection = object()

    def fake_getter(name: str) -> Any:
        assert name == "intents"
        return sentinel_collection

    monkeypatch.setattr(routes, "_collection_getter", fake_getter)

    repository = routes.get_intent_repository()

    assert isinstance(repository, routes.MongoIntentRepository)
    assert repository._collection is sentinel_collection