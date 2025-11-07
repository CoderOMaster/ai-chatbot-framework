import types
import asyncio
from fastapi.testclient import TestClient

import app.main as main_mod


async def _noop_async(*args, **kwargs):
    return None


def test_startup_and_shutdown_calls_close_mongo_and_endpoints(monkeypatch):
    called = {"closed": 0, "init": 0}

    async def fake_init_dm():
        called["init"] += 1

    def fake_close():
        called["closed"] += 1

    # Patch init_dialogue_manager and close_mongo_client used in lifespan
    monkeypatch.setattr(main_mod, "close_mongo_client", fake_close, raising=True)
    monkeypatch.setattr(main_mod, "init_dialogue_manager", fake_init_dm, raising=True)

    with TestClient(main_mod.app) as client:
        # Startup should have been called
        assert called["init"] == 1
        # Endpoints work
        r = client.get("/live")
        assert r.status_code == 200
        assert r.json() == {"status": "alive"}

        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["message"].startswith("Welcome to AI Chatbot Framework API")

    # After context manager exit, shutdown should have called close
    assert called["closed"] == 1


def test_cors_middleware_added():
    # Ensure CORS middleware is present
    from fastapi.middleware.cors import CORSMiddleware

    cors_classes = [mw.cls for mw in main_mod.app.user_middleware]
    assert CORSMiddleware in cors_classes


def test_static_mount_present():
    # Check that static files are mounted under /static
    static_routes = [r for r in main_mod.app.routes if getattr(r, "path", None) == "/static/{path:path}"]
    assert static_routes, "Static files should be mounted at /static"