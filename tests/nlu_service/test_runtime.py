import importlib
import sys
import types
import asyncio
import os

import pytest
from fastapi.testclient import TestClient


class FakePipeline:
    def __init__(self, kind="traditional", load_ok=True):
        self.kind = kind
        self._load_ok = load_ok

    def load(self, model_dir):
        # Simulate model load result
        self.model_dir = model_dir
        return self._load_ok

    def process(self, doc):
        text = doc.get("text", "")
        return {
            "intent": {"name": f"{self.kind}:intent", "text": text},
            "entities": {"items": []},
        }


@pytest.fixture
def inject_fakes(monkeypatch):
    """Inject fake pipeline utils and nlu pipeline types before importing runtime."""
    # Create fake pipeline_utils with async constructors
    fake_utils = types.ModuleType("app.bot.nlu.pipeline_utils")
    async def create_ml_pipeline():
        return FakePipeline(kind="traditional", load_ok=True)
    async def create_zero_shot_pipeline():
        return FakePipeline(kind="llm", load_ok=True)
    async def train_pipeline():
        pass
    fake_utils.create_ml_pipeline = create_ml_pipeline
    fake_utils.create_zero_shot_pipeline = create_zero_shot_pipeline
    fake_utils.train_pipeline = train_pipeline

    # Create fake nlu.pipeline module just to satisfy type import
    fake_nlu_pipeline = types.ModuleType("app.bot.nlu.pipeline")
    class NLUPipeline:  # noqa: N801 (match expected name)
        pass
    fake_nlu_pipeline.NLUPipeline = NLUPipeline

    # Fake settings
    fake_common_config = types.ModuleType("ai_chatbot_common.config")
    def get_settings():
        return types.SimpleNamespace(MODELS_DIR="/models", SPACY_LANG_MODEL="xx_core_web_sm")
    fake_common_config.get_settings = get_settings

    # Install fakes
    monkeypatch.setitem(sys.modules, "app.bot.nlu.pipeline_utils", fake_utils)
    monkeypatch.setitem(sys.modules, "app.bot.nlu.pipeline", fake_nlu_pipeline)
    monkeypatch.setitem(sys.modules, "ai_chatbot_common.config", fake_common_config)

    # Ensure fresh import of runtime each time
    for mod in list(sys.modules):
        if mod.startswith("nlu_service.runtime"):
            sys.modules.pop(mod)

    rt = importlib.import_module("nlu_service.runtime")
    return rt


def test_load_models_selects_traditional_pipeline_by_default(monkeypatch, inject_fakes):
    rt = inject_fakes
    monkeypatch.delenv("NLU_PIPELINE", raising=False)

    asyncio.run(rt.load_models_async())
    out = rt.predict("hello")
    assert out["intent"]["name"].startswith("traditional:"), out


def test_load_models_selects_llm_pipeline_when_configured(monkeypatch, inject_fakes):
    rt = inject_fakes
    monkeypatch.setenv("NLU_PIPELINE", "llm")

    asyncio.run(rt.load_models_async())
    out = rt.predict("hi")
    assert out["intent"]["name"].startswith("llm:"), out


def test_health_endpoint_ok(monkeypatch, inject_fakes):
    rt = inject_fakes
    # Force models to load
    asyncio.run(rt.load_models_async())
    # Ensure memory check passes deterministically
    monkeypatch.setenv("HEALTH_MAX_RSS_MB", "999999")
    monkeypatch.setattr(rt, "_memory_ok", lambda threshold_mb: True)

    with TestClient(rt.app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"ok": True}


def test_health_endpoint_503_when_not_loaded(monkeypatch, inject_fakes):
    rt = inject_fakes
    # Ensure pipeline is None
    rt._PIPELINE = None
    with TestClient(rt.app) as client:
        res = client.get("/health")
        assert res.status_code == 503
        assert "model not loaded" in res.text


def test_health_endpoint_503_when_memory_high(monkeypatch, inject_fakes):
    rt = inject_fakes
    asyncio.run(rt.load_models_async())
    monkeypatch.setattr(rt, "_memory_ok", lambda threshold_mb: False)
    with TestClient(rt.app) as client:
        res = client.get("/health")
        assert res.status_code == 503
        assert "memory high" in res.text


def test_predict_api_success(monkeypatch, inject_fakes):
    rt = inject_fakes
    asyncio.run(rt.load_models_async())
    with TestClient(rt.app) as client:
        res = client.post("/predict", json={"text": "hello", "context": {}})
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"intent", "entities"}
        assert body["intent"]["name"].startswith("traditional:")


def test_predict_api_handles_exception(monkeypatch, inject_fakes):
    rt = inject_fakes
    asyncio.run(rt.load_models_async())
    # Force predict() to raise
    monkeypatch.setattr(rt, "predict", lambda text: (_ for _ in ()).throw(Exception("boom")))
    with TestClient(rt.app) as client:
        res = client.post("/predict", json={"text": "x", "context": {}})
        assert res.status_code == 500
        assert "boom" in res.text
def test_startup_event_loads_models(monkeypatch, inject_fakes):
    rt = inject_fakes
    # Ensure fresh state
    rt._PIPELINE = None
    # Speed up memory check
    monkeypatch.setattr(rt, "_memory_ok", lambda threshold_mb: True)
    with TestClient(rt.app) as client:
        # Startup should have loaded the model
        assert rt._PIPELINE is not None
        res = client.get("/health")
        assert res.status_code == 200


def test_predict_function_raises_if_not_initialized(inject_fakes):
    rt = inject_fakes
    rt._PIPELINE = None
    with pytest.raises(RuntimeError):
        rt.predict("hello")


def test_memory_ok_returns_true_on_exception(monkeypatch, inject_fakes):
    rt = inject_fakes
    class Boom:
        def memory_info(self):
            raise RuntimeError("psutil broke")
    class FakeProc:
        def __init__(self, pid):
            pass
        def memory_info(self):
            raise RuntimeError("boom")
    # Make psutil.Process raise
    import psutil as real_psutil
    monkeypatch.setattr(real_psutil, "Process", lambda pid: FakeProc(pid))
    assert rt._memory_ok(1) is True
def test_load_models_sync_wrapper(monkeypatch, inject_fakes):
    rt = inject_fakes
    # Ensure env defaults to traditional path
    monkeypatch.delenv("NLU_PIPELINE", raising=False)
    # Should not raise even without running event loop
    rt.load_models()
    out = rt.predict("sync")
    assert out["intent"]["name"].startswith("traditional:")