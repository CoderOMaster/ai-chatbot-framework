import json
from fastapi.testclient import TestClient

# Import module under test
import app.bot.nlu.nlu_service.api as api


class DummyPipeline:
    def __init__(self, should_fail_load=False, result=None):
        self.should_fail_load = should_fail_load
        self._result = result or {
            "intent": "greet",
            "entities": [{"entity": "name", "value": "Alice"}],
            "score": 0.99,
        }

    def load(self, model_dir: str):
        if self.should_fail_load:
            raise RuntimeError("boom")

    def process(self, message):
        return dict(self._result)


async def _return_pipeline(pipeline: DummyPipeline):
    return pipeline


def test_health_ok_even_if_model_load_fails(monkeypatch):
    # Patch the already-imported symbol in api module
    dummy = DummyPipeline(should_fail_load=True)

    async def fake_get_pipeline():
        return dummy

    monkeypatch.setattr(api, "get_pipeline", fake_get_pipeline)

    with TestClient(api.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_predict_success_with_context(monkeypatch):
    expected = {
        "intent": "order_pizza",
        "entities": [{"entity": "size", "value": "large"}],
        "raw": {
            "intent": "order_pizza",
            "entities": [{"entity": "size", "value": "large"}],
        },
    }

    class P(DummyPipeline):
        def process(self, message):
            assert message["text"] == "I want a large pizza"
            assert message["context"] == {"source": "test"}
            return {
                "intent": "order_pizza",
                "entities": [{"entity": "size", "value": "large"}],
            }

    async def fake_get_pipeline():
        return P()

    monkeypatch.setattr(api, "get_pipeline", fake_get_pipeline)

    with TestClient(api.app) as client:
        r = client.post(
            "/predict",
            json={"text": "I want a large pizza", "context": {"source": "test"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == expected["intent"]
        assert body["entities"] == expected["entities"]
        # raw should contain the underlying pipeline output
        assert body["raw"] == expected["raw"]


def test_predict_503_when_pipeline_not_ready(monkeypatch):
    # Initialize with a valid pipeline first (startup), then set to None
    async def fake_get_pipeline():
        return DummyPipeline()

    monkeypatch.setattr(api, "get_pipeline", fake_get_pipeline)

    with TestClient(api.app) as client:
        # Simulate pipeline not ready
        api.STATE["pipeline"] = None
        r = client.post("/predict", json={"text": "hi"})
        assert r.status_code == 503
        assert "pipeline not ready" in r.text


def test_health_503_when_not_loaded(monkeypatch):
    async def fake_get_pipeline():
        return DummyPipeline()

    monkeypatch.setattr(api, "get_pipeline", fake_get_pipeline)

    with TestClient(api.app) as client:
        api.STATE["loaded"] = False
        r = client.get("/health")
        assert r.status_code == 503
        assert "model not loaded" in r.text
        # put state back for other tests
        api.STATE["loaded"] = True
def test_predict_defaults_context_when_omitted(monkeypatch):
    class P(DummyPipeline):
        def process(self, message):
            assert message["text"] == "hello"
            assert message["context"] == {}
            return {"intent": "greet", "entities": []}

    async def fake_get_pipeline():
        return P()

    monkeypatch.setattr(api, "get_pipeline", fake_get_pipeline)

    with TestClient(api.app) as client:
        r = client.post("/predict", json={"text": "hello"})
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "greet"
        assert body["entities"] == []
        assert body["raw"]["intent"] == "greet"


def test_startup_load_uses_env_model_dir(monkeypatch):
    captured = {"dir": None}

    class P(DummyPipeline):
        def load(self, model_dir: str):
            captured["dir"] = model_dir

    async def fake_get_pipeline():
        return P()

    monkeypatch.setattr(api, "get_pipeline", fake_get_pipeline)
    monkeypatch.setenv("MODEL_DIR", "/custom/models")

    with TestClient(api.app) as client:
        # startup runs and sets captured dir
        r = client.get("/health")
        assert r.status_code == 200

    assert captured["dir"] == "/custom/models"