import importlib
import sys
from types import ModuleType
from fastapi import APIRouter
from fastapi.testclient import TestClient


def import_main_with_stubs():
    # Stub ai_chatbot_common.config
    cfg_pkg = ModuleType("ai_chatbot_common.config")

    class SettingsObj:
        def dict(self):
            return {"MONGODB_HOST": "mongodb://stub", "MONGODB_DATABASE": "chatbot"}

    def get_settings():
        return SettingsObj()

    cfg_pkg.get_settings = get_settings

    # Stub ai_chatbot_common.database
    db_pkg = ModuleType("ai_chatbot_common.database")

    async def wait_for_db(*args, **kwargs):
        return None

    def get_db():
        return object()

    db_pkg.wait_for_db = wait_for_db
    db_pkg.get_db = get_db

    # Install stubs into sys.modules before importing app.main
    root_pkg = ModuleType("ai_chatbot_common")
    sys.modules["ai_chatbot_common"] = root_pkg
    sys.modules["ai_chatbot_common.config"] = cfg_pkg
    sys.modules["ai_chatbot_common.database"] = db_pkg

    # Stub heavy or DB-dependent modules imported by app.main
    # DialogueManager import in dependencies
    dm_mod = ModuleType("app.bot.dialogue_manager.dialogue_manager")

    class DummyDM:
        @classmethod
        async def from_config(cls):
            return cls()

    dm_mod.DialogueManager = DummyDM
    sys.modules["app.bot.dialogue_manager.dialogue_manager"] = dm_mod

    # Routers that app.main includes; provide minimal APIRouter instances
    for mod_name in [
        "app.admin.bots.routes",
        "app.admin.entities.routes",
        "app.admin.intents.routes",
        "app.admin.train.routes",
        "app.admin.test.routes",
        "app.admin.integrations.routes",
        "app.admin.chatlogs.routes",
        "app.bot.channels.rest.routes",
        "app.bot.channels.facebook.routes",
    ]:
        m = ModuleType(mod_name)
        m.router = APIRouter()
        sys.modules[mod_name] = m

    main = importlib.import_module("app.main")
    importlib.reload(main)  # ensure reload uses our stubs
    return main


def test_live_endpoint_ok(monkeypatch):
    main = import_main_with_stubs()
    with TestClient(main.app) as client:
        r = client.get("/live")
        assert r.status_code == 200
        assert r.json() == {"status": "alive"}


def test_root_message(monkeypatch):
    main = import_main_with_stubs()
    with TestClient(main.app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["message"].startswith("Welcome to AI Chatbot Framework API")


def test_ready_ok_when_db_and_dm_ready(monkeypatch):
    main = import_main_with_stubs()

    async def ok_wait_for_db(max_retries=1, delay_seconds=0.1):
        return None

    async def get_dm():
        return object()

    monkeypatch.setattr(main, "wait_for_db", ok_wait_for_db, raising=True)
    monkeypatch.setattr(main, "get_dialogue_manager", get_dm, raising=True)

    with TestClient(main.app) as client:
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_ready_503_when_database_not_ready(monkeypatch):
    main = import_main_with_stubs()

    async def failing_wait_for_db(max_retries=1, delay_seconds=0.1):
        raise RuntimeError("db down")

    async def get_dm():
        return object()

    monkeypatch.setattr(main, "wait_for_db", failing_wait_for_db, raising=True)
    monkeypatch.setattr(main, "get_dialogue_manager", get_dm, raising=True)

    with TestClient(main.app) as client:
        r = client.get("/ready")
        assert r.status_code == 503
        assert "database not ready" in r.text


def test_ready_503_when_dialogue_manager_not_ready(monkeypatch):
    main = import_main_with_stubs()

    async def ok_wait_for_db(max_retries=1, delay_seconds=0.1):
        return None

    async def get_dm_none():
        return None

    monkeypatch.setattr(main, "wait_for_db", ok_wait_for_db, raising=True)
    monkeypatch.setattr(main, "get_dialogue_manager", get_dm_none, raising=True)

    with TestClient(main.app) as client:
        r = client.get("/ready")
        assert r.status_code == 503
        assert "dialogue manager not ready" in r.text


def test_lifespan_initializes_dm_even_if_db_wait_fails(monkeypatch):
    main = import_main_with_stubs()
    called = {"init": False}

    async def fake_init_dialogue_manager():
        called["init"] = True

    async def failing_wait_for_db(*args, **kwargs):
        raise RuntimeError("db not ready at startup")

    # Patch startup functions before TestClient context enters
    monkeypatch.setattr(main, "init_dialogue_manager", fake_init_dialogue_manager, raising=True)
    monkeypatch.setattr(main, "wait_for_db", failing_wait_for_db, raising=True)

    with TestClient(main.app) as client:
        # lifespan should not crash
        assert called["init"] is True
        # liveness works regardless
        r_live = client.get("/live")
        assert r_live.status_code == 200
        # readiness should reflect db failure
        r_ready = client.get("/ready")
        assert r_ready.status_code == 503