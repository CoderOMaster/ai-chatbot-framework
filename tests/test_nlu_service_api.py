import os
import sys
import types
import pytest
import importlib
from importlib import reload


class _FakePsutil:
    class _Mem:
        percent = 12.34
    @staticmethod
    def virtual_memory():
        return _FakePsutil._Mem()


@pytest.mark.asyncio
async def test_startup_loads_models_and_health_ok(monkeypatch):
    # Stub psutil before importing module
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)

    # Prepare a fake pipeline with load() and process()
    class FakePipeline:
        def __init__(self):
            self.loaded = False
        def load(self, model_dir):
            assert model_dir == os.environ.get("MODEL_DIR", "/models")
            self.loaded = True
        def process(self, msg):
            return {"intent": {"name": "greet", "confidence": 0.9},
                    "intent_ranking": [{"name": "greet", "confidence": 0.9}],
                    "entities": {}}  # Changed from [] to {} to match expected dict type

    async def fake_get_pipeline():
        return FakePipeline()

    # Patch the get_pipeline function in the pipeline_utils module
    monkeypatch.setattr("app.bot.nlu.pipeline_utils.get_pipeline", fake_get_pipeline)
    
    # Set environment variable
    monkeypatch.setenv("MODEL_DIR", "/tmp/models")

    # Import module fresh to reset globals
    api = importlib.import_module("app.nlu_service.api")
    reload(api)

    # Ensure globals are reset
    api._pipeline = None
    api._model_loaded = False

    # Invoke startup hook
    await api.load_models()
    assert api._model_loaded is True
    assert isinstance(api._pipeline, FakePipeline)

    # Health endpoint reflects loaded state
    health = await api.health()
    assert isinstance(health, dict)
    assert health.get("ok") is True
    assert "memory_percent" in health

    # Predict endpoint returns structured response
    req = api.PredictRequest(text="hello")
    resp = await api.predict(req)
    assert resp.intent["name"] == "greet"
    assert resp.intent_ranking and resp.intent_ranking[0]["name"] == "greet"
    assert resp.entities == {}  # Changed from [] to {} to match expected dict type


@pytest.mark.asyncio
async def test_predict_returns_503_when_model_not_ready(monkeypatch):
    # Stub psutil before importing module
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)

    api = importlib.import_module("app.nlu_service.api")
    reload(api)

    # Explicitly mark pipeline not ready
    api._pipeline = None
    api._model_loaded = False

    with pytest.raises(Exception) as exc:
        await api.predict(api.PredictRequest(text="hi"))
    # FastAPI HTTPException 503
    assert getattr(exc.value, "status_code", None) == 503


@pytest.mark.asyncio
async def test_startup_failure_sets_model_not_loaded(monkeypatch):
    # Stub psutil before importing module
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)

    async def failing_get_pipeline():
        raise RuntimeError("boom")

    # Patch the get_pipeline function before importing the API module
    monkeypatch.setattr("app.bot.nlu.pipeline_utils.get_pipeline", failing_get_pipeline)

    api = importlib.import_module("app.nlu_service.api")
    reload(api)

    api._pipeline = None
    api._model_loaded = True

    await api.load_models()
    assert api._model_loaded is False
    health = await api.health()
    assert health.get("ok") is False