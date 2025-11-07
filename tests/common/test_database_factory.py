import types
import asyncio
import pytest


def _reset(dbmod):
    # ensure caches and clients cleared between tests
    dbmod.close_mongo_client()


@pytest.fixture
def dbmod(monkeypatch):
    import importlib
    mod = importlib.import_module("app.common.database")
    _reset(mod)
    try:
        yield mod
    finally:
        _reset(mod)


def test_get_mongo_client_caches_by_params(monkeypatch, dbmod):
    created = []

    class DummyClient:
        def __init__(self, host, **kwargs):
            self.host = host
            self.kwargs = kwargs
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

        def get_database(self, name):
            return types.SimpleNamespace(name=name)

    monkeypatch.setattr(dbmod, "AsyncIOMotorClient", DummyClient)

    SettingsA = types.SimpleNamespace(
        MONGODB_HOST="mongodb://a:27017",
        MONGODB_DATABASE="dbA",
        MONGODB_MAX_POOL_SIZE=50,
        MONGODB_CONNECT_TIMEOUT_MS=1000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
    )
    SettingsB = types.SimpleNamespace(
        MONGODB_HOST="mongodb://a:27017",
        MONGODB_DATABASE="dbB",
        MONGODB_MAX_POOL_SIZE=75,  # different => different client
        MONGODB_CONNECT_TIMEOUT_MS=1000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
    )

    c1 = dbmod.get_mongo_client(SettingsA)
    c2 = dbmod.get_mongo_client(SettingsA)
    c3 = dbmod.get_mongo_client(SettingsB)

    assert c1 is c2
    assert c1 is not c3
    assert created[0].kwargs["maxPoolSize"] == 50
    assert created[1].kwargs["maxPoolSize"] == 75


def test_build_client_fallback_to_minimal_signature(monkeypatch, dbmod):
    class FallbackClient:
        def __init__(self, host, **kwargs):
            if kwargs:
                # simulate client that does not support kwargs
                raise TypeError("unexpected kwargs")
            self.host = host
            self.closed = False

        def close(self):
            self.closed = True

        def get_database(self, name):
            return types.SimpleNamespace(name=name)

    monkeypatch.setattr(dbmod, "AsyncIOMotorClient", FallbackClient)

    Settings = types.SimpleNamespace(
        MONGODB_HOST="mongodb://fallback:27017",
        MONGODB_DATABASE="dbF",
        MONGODB_MAX_POOL_SIZE=50,
        MONGODB_CONNECT_TIMEOUT_MS=1000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
    )

    c = dbmod.get_mongo_client(Settings)
    assert isinstance(c, FallbackClient)
    assert c.host == "mongodb://fallback:27017"


def test_close_mongo_client_closes_and_clears_cache(monkeypatch, dbmod):
    created = []

    class DummyClient:
        def __init__(self, host, **kwargs):
            self.host = host
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

        def get_database(self, name):
            return types.SimpleNamespace(name=name)

    monkeypatch.setattr(dbmod, "AsyncIOMotorClient", DummyClient)

    S1 = types.SimpleNamespace(
        MONGODB_HOST="mongodb://one:27017",
        MONGODB_DATABASE="db1",
        MONGODB_MAX_POOL_SIZE=1,
        MONGODB_CONNECT_TIMEOUT_MS=1000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
    )
    S2 = types.SimpleNamespace(
        MONGODB_HOST="mongodb://two:27017",
        MONGODB_DATABASE="db2",
        MONGODB_MAX_POOL_SIZE=2,
        MONGODB_CONNECT_TIMEOUT_MS=1000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
    )

    c1 = dbmod.get_mongo_client(S1)
    c2 = dbmod.get_mongo_client(S2)
    assert len(created) == 2

    dbmod.close_mongo_client()
    assert c1.closed and c2.closed

    # cache cleared, new instance should be created for S1
    c1_new = dbmod.get_mongo_client(S1)
    assert c1_new is not c1
    assert not c1_new.closed


@pytest.mark.asyncio
async def test_get_db_returns_configured_database(monkeypatch, dbmod):
    class DummyClient:
        def __init__(self, host, **kwargs):
            self.host = host

        def get_database(self, name):
            return types.SimpleNamespace(name=name)

    monkeypatch.setattr(dbmod, "AsyncIOMotorClient", DummyClient)

    # Patch get_settings to return our dummy settings
    import ai_chatbot_common.config as cfg

    monkeypatch.setattr(cfg, "get_settings", lambda: types.SimpleNamespace(
        MONGODB_HOST="mongodb://host:27017",
        MONGODB_DATABASE="expected_db",
        MONGODB_MAX_POOL_SIZE=10,
        MONGODB_CONNECT_TIMEOUT_MS=1000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
        MONGODB_HEALTHCHECK_ENABLED=True,
    ))

    db = await dbmod.get_db()
    assert getattr(db, "name", None) == "expected_db"


@pytest.mark.asyncio
async def test_check_db_health_pings_db(monkeypatch, dbmod):
    class DummyDB:
        def __init__(self):
            self.pings = []

        async def command(self, cmd):
            self.pings.append(cmd)
            return {"ok": 1}

    async def fake_get_db():
        return DummyDB()

    monkeypatch.setattr(dbmod, "get_db", fake_get_db)

    healthy = await dbmod.check_db_health()
    assert healthy is True
    # ensure our fake db saw the ping
    db = await fake_get_db()
    assert {"ping": 1} in db.pings