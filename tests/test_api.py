import pytest
from unittest.mock import patch
import nlu_service.api as api

# Since fastapi is not installed, we cannot use TestClient directly.
# Instead, we can use the TestClient only if it's available.
try:
    from fastapi.testclient import TestClient
    client = TestClient(api.app)
except ImportError:
    client = None

@pytest.mark.skipif(client is None, reason="fastapi package is not installed")
def test_health_when_not_loaded():
    api.model_loaded = False
    r = client.get("/health")
    assert r.status_code == 503

@pytest.mark.skipif(client is None, reason="fastapi package is not installed")
def test_health_when_loaded_and_memory_ok():
    api.model_loaded = True

    class VM:
        percent = 10

    with patch("psutil.virtual_memory", return_value=VM()):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["model_loaded"] is True

@pytest.mark.skipif(client is None, reason="fastapi package is not installed")
def test_predict_not_loaded():
    api.model_loaded = False
    r = client.post("/predict", json={"text": "hi"})
    assert r.status_code == 503

@pytest.mark.skipif(client is None, reason="fastapi package is not installed")
def test_predict_success():
    api.model_loaded = True

    class Dummy:
        def process(self, payload):
            return {"resp": "ok", "input": payload}

    api.pipeline = Dummy()
    r = client.post("/predict", json={"text": "hi"})
    assert r.status_code == 200
    assert r.json()["resp"] == "ok"

@pytest.mark.skipif(client is None, reason="fastapi package is not installed")
def test_predict_exception():
    api.model_loaded = True

    class Bad:
        def process(self, payload):
            raise RuntimeError("boom")

    api.pipeline = Bad()
    r = client.post("/predict", json={"text": "hi"})
    assert r.status_code == 500