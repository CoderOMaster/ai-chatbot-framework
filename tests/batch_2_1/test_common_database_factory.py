import asyncio
import sys
import types
import importlib.util
import pytest


def import_with_stubbed_settings(module_path, module_name="aicf_common_database_test"):
    # Stub ai_chatbot_common.config.get_settings before importing target module
    cfg_mod = types.ModuleType("ai_chatbot_common.config")

    class SettingsObj:
        MONGODB_HOST = "mongodb://stubbed-host:27017"
        MONGODB_DATABASE = "stubdb"

    def get_settings():  # noqa: D401
        return SettingsObj()

    cfg_mod.get_settings = get_settings

    # Install ai_chatbot_common package and submodule in sys.modules
    pkg_mod = types.ModuleType("ai_chatbot_common")
    sys.modules["ai_chatbot_common"] = pkg_mod
    sys.modules["ai_chatbot_common.config"] = cfg_mod

    # Stub motor.motor_asyncio to avoid external dependency
    motor_pkg = types.ModuleType("motor")
    motor_asyncio = types.ModuleType("motor.motor_asyncio")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_database(self, name):
            return types.SimpleNamespace(name=name)

    class DummyDB:
        pass

    motor_asyncio.AsyncIOMotorClient = DummyClient
    motor_asyncio.AsyncIOMotorDatabase = DummyDB

    sys.modules["motor"] = motor_pkg
    sys.modules["motor.motor_asyncio"] = motor_asyncio

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_get_mongo_client_builds_client_with_envs(monkeypatch):
    mod = import_with_stubbed_settings("ai-chatbot-framework/app/common/database.py")

    # Ensure no caching from prior tests
    mod.get_mongo_client.cache_clear()

    # Prepare env overrides
    monkeypatch.setenv("MONGODB_MAX_POOL_SIZE", "123")
    monkeypatch.setenv("MONGODB_CONNECT_TIMEOUT_MS", "1111")
    monkeypatch.setenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "2222")
    monkeypatch.setenv("MONGODB_SOCKET_TIMEOUT_MS", "3333")

    calls = {}

    class FakeClient:
        def __init__(self, uri, **kwargs):
            calls["uri"] = uri
            calls["kwargs"] = kwargs

    # Patch class in module namespace
    monkeypatch.setattr(mod, "AsyncIOMotorClient", FakeClient)

    client = mod.get_mongo_client()

    assert isinstance(client, FakeClient)
    assert calls["uri"] == "mongodb://stubbed-host:27017"
    assert calls["kwargs"]["maxPoolSize"] == 123
    assert calls["kwargs"]["connectTimeoutMS"] == 1111
    assert calls["kwargs"]["serverSelectionTimeoutMS"] == 2222
    assert calls["kwargs"]["socketTimeoutMS"] == 3333
    assert calls["kwargs"]["retryWrites"] is True
    assert calls["kwargs"]["uuidRepresentation"] == "standard"


def test_get_db_returns_named_database(monkeypatch):
    mod = import_with_stubbed_settings("ai-chatbot-framework/app/common/database.py")

    class FakeDB:
        name = "stubdb"
        async def command(self, *_args, **_kwargs):
            return {"ok": 1}

    class FakeClient:
        def get_database(self, name):
            return FakeDB()

    monkeypatch.setattr(mod, "get_mongo_client", lambda: FakeClient())

    db = mod.get_db()
    assert isinstance(db, FakeDB)
    assert db.name == "stubdb"


@pytest.mark.asyncio
async def test_wait_for_db_success_and_retry(monkeypatch):
    mod = import_with_stubbed_settings("ai-chatbot-framework/app/common/database.py")

    class FakeDB:
        def __init__(self):
            self.calls = 0
        async def command(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temp failure")
            return {"ok": 1}

    db = FakeDB()
    monkeypatch.setattr(mod, "get_db", lambda: db)

    slept = []

    async def fake_sleep(t):
        slept.append(t)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await mod.wait_for_db(max_retries=3, delay_seconds=0.5)

    assert db.calls == 2  # one failure, one success
    assert slept == [0.5]  # first backoff only


@pytest.mark.asyncio
async def test_wait_for_db_raises_after_retries(monkeypatch):
    mod = import_with_stubbed_settings("ai-chatbot-framework/app/common/database.py")

    class FakeDB:
        def __init__(self):
            self.calls = 0
        async def command(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("always down")

    db = FakeDB()
    monkeypatch.setattr(mod, "get_db", lambda: db)

    sleeps = []
    async def fake_sleep(t):
        sleeps.append(t)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(RuntimeError):
        await mod.wait_for_db(max_retries=3, delay_seconds=0.1)

    # Should have slept max_retries times minus one (no sleep after final attempt)
    assert sleeps == [0.1, 0.2, 0.4][:3]


@pytest.mark.asyncio
async def test_db_dependency_yields_db(monkeypatch):
    mod = import_with_stubbed_settings("ai-chatbot-framework/app/common/database.py")

    class FakeDB:
        pass

    sentinel_db = FakeDB()
    monkeypatch.setattr(mod, "get_db", lambda: sentinel_db)

    agen = mod.db_dependency()
    db = await agen.__anext__()
    assert db is sentinel_db
    await agen.aclose()