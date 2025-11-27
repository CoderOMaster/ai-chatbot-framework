import pytest
from typing import Any, Optional
from fastapi import HTTPException
import httpx

import app.admin.train.routes as routes
import app.bot.nlu.pipeline_utils as pipeline_utils


@pytest.fixture(autouse=True)
def restore_enqueue_and_job_status(monkeypatch):
    """Ensure we restore any patched attributes on the routes module between tests."""
    original_enqueue = getattr(routes, "enqueue_training_job", None)
    original_get_job_status = getattr(routes, "get_job_status", None)
    yield
    if original_enqueue is not None:
        monkeypatch.setattr(routes, "enqueue_training_job", original_enqueue, raising=False)
    if original_get_job_status is not None:
        monkeypatch.setattr(routes, "get_job_status", original_get_job_status, raising=False)


class MockResponse:
    def __init__(self, data: Any = None, raise_err: Optional[Exception] = None):
        self._data = data or {}
        self._raise_err = raise_err

    def raise_for_status(self) -> None:
        if self._raise_err:
            raise self._raise_err

    def json(self) -> Any:
        return self._data


class DummyAsyncClient:
    def __init__(self, method: str = "GET", response: Optional[MockResponse] = None, raise_on_call: bool = False):
        self._method = method
        self._response = response or MockResponse({})
        self._raise_on_call = raise_on_call

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        if self._raise_on_call:
            raise httpx.HTTPError("get error")
        return self._response

    async def post(self, url: str, json: Any = None):
        if self._raise_on_call:
            raise httpx.HTTPError("post error")
        return self._response

    async def put(self, url: str, json: Any = None):
        if self._raise_on_call:
            raise httpx.HTTPError("put error")
        return self._response

    async def delete(self, url: str):
        if self._raise_on_call:
            raise httpx.HTTPError("delete error")
        return self._response


@pytest.mark.asyncio
async def test__call_intents_api_get_success(monkeypatch):
    """_call_intents_api should return JSON data for GET when the internal API responds successfully."""
    data = {"id": "intent1", "trainingData": []}
    mock_resp = MockResponse(data)

    def fake_client(*args, **kwargs):
        return DummyAsyncClient(method="GET", response=mock_resp)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    result = await routes._call_intents_api("GET", "/admin/intents/intent1")
    assert result == data


@pytest.mark.asyncio
async def test__call_intents_api_unsupported_method():
    """_call_intents_api should raise ValueError for unsupported HTTP methods."""
    with pytest.raises(ValueError):
        await routes._call_intents_api("PATCH", "/admin/intents/intent1")


@pytest.mark.asyncio
async def test__call_intents_api_http_error(monkeypatch):
    """_call_intents_api should convert httpx.HTTPError into HTTPException with status 500."""

    def fake_client(*args, **kwargs):
        return DummyAsyncClient(method="GET", response=MockResponse(), raise_on_call=True)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    with pytest.raises(HTTPException) as ctx:
        await routes._call_intents_api("GET", "/admin/intents/intent1")

    assert ctx.value.status_code == 500


@pytest.mark.asyncio
async def test_save_training_data_success(monkeypatch):
    """save_training_data should verify intent exists and update it with provided training data."""

    calls = []

    async def fake_call(method: str, endpoint: str, data: Any = None):
        calls.append((method, endpoint, data))
        if method == "GET":
            return {"id": "intentX", "trainingData": ["old"]}
        if method == "PUT":
            return {"status": "ok"}

    monkeypatch.setattr(routes, "_call_intents_api", fake_call)

    training = [{"text": "hello"}, {"text": "hi"}]
    res = await routes.save_training_data("intentX", training)

    assert res["status"] == "success"
    assert res["intent_id"] == "intentX"
    assert res["data_count"] == 2
    # ensure GET then PUT called
    assert calls[0][0] == "GET"
    assert calls[1][0] == "PUT"


@pytest.mark.asyncio
async def test_save_training_data_intent_not_found(monkeypatch):
    """save_training_data should raise 404 when intent is not found from internal API."""

    async def fake_call(method: str, endpoint: str, data: Any = None):
        raise HTTPException(status_code=404)

    monkeypatch.setattr(routes, "_call_intents_api", fake_call)

    with pytest.raises(HTTPException) as ctx:
        await routes.save_training_data("missing", [])
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_save_training_data_put_failure(monkeypatch):
    """save_training_data should raise HTTPException 500 if updating the intent fails."""

    async def fake_call(method: str, endpoint: str, data: Any = None):
        if method == "GET":
            return {"id": "intentY"}
        raise HTTPException(status_code=500, detail="upstream error")

    monkeypatch.setattr(routes, "_call_intents_api", fake_call)

    with pytest.raises(HTTPException) as ctx:
        await routes.save_training_data("intentY", [{"text": "x"}])

    assert ctx.value.status_code == 500


@pytest.mark.asyncio
async def test_get_training_data_success(monkeypatch):
    """get_training_data should return the training data and correct count for the intent."""

    async def fake_call(method: str, endpoint: str, data: Any = None):
        return {"id": "intentZ", "trainingData": [{"text": "a"}]}

    monkeypatch.setattr(routes, "_call_intents_api", fake_call)

    res = await routes.get_training_data("intentZ")
    assert res["intent_id"] == "intentZ"
    assert isinstance(res["data"], list) and res["count"] == 1


@pytest.mark.asyncio
async def test_get_training_data_not_found(monkeypatch):
    """get_training_data should raise 404 when intent is not found."""

    async def fake_call(method: str, endpoint: str, data: Any = None):
        raise HTTPException(status_code=404)

    monkeypatch.setattr(routes, "_call_intents_api", fake_call)

    with pytest.raises(HTTPException) as ctx:
        await routes.get_training_data("nope")
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_build_models_success(monkeypatch):
    """build_models should enqueue a training job and return job metadata."""

    async def fake_enqueue(bot_id: str):
        return "job-abc"

    monkeypatch.setattr(routes, "enqueue_training_job", fake_enqueue)

    res = await routes.build_models(bot_id="mybot")
    assert res["status"] == "training_queued"
    assert res["job_id"] == "job-abc"
    assert res["bot_id"] == "mybot"


@pytest.mark.asyncio
async def test_build_models_enqueue_failure(monkeypatch):
    """build_models should raise HTTPException when enqueueing fails."""

    async def fake_enqueue(bot_id: str):
        raise Exception("sqs error")

    monkeypatch.setattr(routes, "enqueue_training_job", fake_enqueue)

    with pytest.raises(HTTPException) as ctx:
        await routes.build_models(bot_id="b")
    assert ctx.value.status_code == 500


@pytest.mark.asyncio
async def test_get_training_job_status_not_found(monkeypatch):
    """get_training_job_status should raise 404 when the job is not found."""

    monkeypatch.setattr(routes, "get_job_status", lambda jid: None)

    with pytest.raises(HTTPException) as ctx:
        await routes.get_training_job_status("job-x")
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_get_training_job_status_success(monkeypatch):
    """get_training_job_status should return a structured status dict when job exists."""

    job = {
        "status": "IN_PROGRESS",
        "progress": 42,
        "bot_id": "bot1",
        "created_at": "t1",
        "updated_at": "t2",
        "error": None,
    }

    monkeypatch.setattr(routes, "get_job_status", lambda jid: job)

    res = await routes.get_training_job_status("job-x")
    assert res["job_id"] == "job-x"
    assert res["status"] == "IN_PROGRESS"
    assert res["progress"] == 42


class DummyTracker:
    def __init__(self):
        self.calls = []

    def update_job_status(self, job_id: str, status: Any, error: Optional[str] = None):
        self.calls.append((job_id, status, error))


@pytest.mark.asyncio
async def test_cancel_training_job_not_found(monkeypatch):
    """cancel_training_job should raise 404 when job is not present."""
    monkeypatch.setattr(routes, "get_job_status", lambda jid: None)

    with pytest.raises(HTTPException) as ctx:
        await routes.cancel_training_job("job-missing")
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_training_job_cannot_cancel_completed(monkeypatch):
    """cancel_training_job should not allow cancelling a COMPLETED job."""
    completed_status = {"status": routes.TrainingJobStatus.COMPLETED.value}
    monkeypatch.setattr(routes, "get_job_status", lambda jid: completed_status)

    with pytest.raises(HTTPException) as ctx:
        await routes.cancel_training_job("job1")
    assert ctx.value.status_code == 400


@pytest.mark.asyncio
async def test_cancel_training_job_cannot_cancel_failed(monkeypatch):
    """cancel_training_job should not allow cancelling a FAILED job."""
    failed_status = {"status": routes.TrainingJobStatus.FAILED.value}
    monkeypatch.setattr(routes, "get_job_status", lambda jid: failed_status)

    with pytest.raises(HTTPException) as ctx:
        await routes.cancel_training_job("job2")
    assert ctx.value.status_code == 400


@pytest.mark.asyncio
async def test_cancel_training_job_success(monkeypatch):
    """cancel_training_job should mark a PENDING job as cancelled by calling the job tracker."""
    pending_status = {"status": routes.TrainingJobStatus.PENDING.value}
    monkeypatch.setattr(routes, "get_job_status", lambda jid: pending_status)

    # Ensure pipeline_utils module has _job_tracker attribute used by the function
    tracker = DummyTracker()
    setattr(pipeline_utils, "_job_tracker", tracker)

    res = await routes.cancel_training_job("job-c1")

    assert res["status"] == "cancelled"
    assert res["job_id"] == "job-c1"
    # verify tracker was called and status passed is the enum member (not its value)
    assert len(tracker.calls) == 1
    called_job_id, called_status, called_error = tracker.calls[0]
    assert called_job_id == "job-c1"
    assert called_error == "Cancelled by user"
    # Status should be the enum member TrainingJobStatus.FAILED
    assert called_status == routes.TrainingJobStatus.FAILED