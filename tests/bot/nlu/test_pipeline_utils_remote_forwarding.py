import os
import json
import types
import pytest

from app.bot.nlu.pipeline_utils import RemoteNLUPipeline, get_pipeline


class DummyResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {"intent": {"intent": "greet", "confidence": 0.9}, "entities": {}}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def test_remote_pipeline_process_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):  # noqa: A002 - shadow
        captured["url"] = url
        captured["json"] = json
        return DummyResponse(200)

    import app.bot.nlu.pipeline_utils as mod
    monkeypatch.setenv("MODEL_FORWARDING_ENDPOINT", "http://nlu:8001/predict")
    monkeypatch.setattr(__import__("requests"), "post", fake_post)

    pipeline = RemoteNLUPipeline("http://nlu:8001/predict")
    result = pipeline.process({"text": "hello"})
    assert result["intent"]["intent"] == "greet"
    assert captured["url"].endswith("/predict")
    assert captured["json"] == {"text": "hello"}


def test_remote_pipeline_process_error_returns_fallback(monkeypatch):
    def fake_post(url, json=None, timeout=None):  # noqa: A002
        raise RuntimeError("boom")

    monkeypatch.setattr(__import__("requests"), "post", fake_post)
    pipeline = RemoteNLUPipeline("http://nlu:8001/predict")
    out = pipeline.process({"text": "hi"})
    assert out["intent"]["intent"] == "fallback"
    assert out["intent"]["confidence"] == 0.0
    assert out["entities"] == {}


@pytest.mark.asyncio
async def test_get_pipeline_prefers_remote_forwarding(monkeypatch):
    monkeypatch.setenv("MODEL_FORWARDING_ENDPOINT", "http://nlu:8001/predict")

    # If remote env is set, we should not attempt to call get_nlu_config
    import app.bot.nlu.pipeline_utils as mod

    called = {"get_nlu_config": 0}

    async def fake_get_nlu_config(name):  # pragma: no cover - should not be called
        called["get_nlu_config"] += 1
        class Dummy:
            pipeline_type = "traditional"
            traditional_settings = types.SimpleNamespace(dict=lambda: {})
        return Dummy()

    monkeypatch.setattr(mod, "get_nlu_config", fake_get_nlu_config)

    pipeline = await get_pipeline()
    assert isinstance(pipeline, RemoteNLUPipeline)
    assert called["get_nlu_config"] == 0