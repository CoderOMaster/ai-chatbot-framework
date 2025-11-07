import types
import pytest
from fastapi.testclient import TestClient


def build_app(monkeypatch):
    # Patch init_dialogue_manager to avoid heavy startup
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.dependencies",
        types.SimpleNamespace(init_dialogue_manager=lambda: None),
    )
    from app.main import app
    return app


@pytest.fixture
def client(monkeypatch):
    app = build_app(monkeypatch)
    with TestClient(app) as c:
        yield c


def test_ready_endpoint(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Welcome" in resp.json()["message"]