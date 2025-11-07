import types
import pytest
from fastapi.testclient import TestClient


def build_app_with_dummy_client(monkeypatch):
    # Avoid heavy startup
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.dependencies",
        types.SimpleNamespace(init_dialogue_manager=lambda: None),
    )

    # Patch close_mongo_client to observe calls
    calls = {"closed": False}

    def fake_close():
        calls["closed"] = True

    monkeypatch.setitem(
        __import__("sys").modules,
        "app.common.database",
        types.SimpleNamespace(close_mongo_client=fake_close),
    )

    from importlib import reload
    import app.main as main
    reload(main)  # ensure it picks our monkeypatch
    return main.app, calls


@pytest.fixture
def app_and_calls(monkeypatch):
    return build_app_with_dummy_client(monkeypatch)


@pytest.fixture
def client(app_and_calls):
    app, _ = app_and_calls
    with TestClient(app) as c:
        yield c


def test_shutdown_closes_mongo_client(app_and_calls, client):
    # closing the TestClient triggers shutdown event
    _, calls = app_and_calls
    assert calls["closed"] is True