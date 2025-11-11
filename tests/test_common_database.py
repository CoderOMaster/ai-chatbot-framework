import types
import importlib
import pytest

pytestmark = pytest.mark.asyncio


class FakeClient:
    def __init__(self, uri, **kwargs):
        self.uri = uri
        self.kwargs = kwargs
        self.admin = self.Admin()

    class Admin:
        def __init__(self):
            self.calls = 0

        async def command(self, name):
            # Default: succeed
            return {"ok": 1}

    def get_database(self, name):
        return {"db": name}


async def test_get_mongo_client_singleton_and_params(monkeypatch):
    import app.common.database as db

    # Reset singleton and patch client class
    monkeypatch.setattr(db, "_client_singleton", None, raising=False)
    monkeypatch.setattr(db, "AsyncIOMotorClient", FakeClient)

    settings = types.SimpleNamespace(
        MONGODB_HOST="mongodb://unit-test:27017",
        MONGODB_DATABASE="chatbot_test",
        MONGODB_MAX_POOL_SIZE=123,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1111,
        MONGODB_CONNECT_TIMEOUT_MS=2222,
        MONGODB_SOCKET_TIMEOUT_MS=3333,
    )

    client1 = db.get_mongo_client(settings)
    client2 = db.get_mongo_client(settings)

    assert client1 is client2, "get_mongo_client should return a singleton instance"
    assert isinstance(client1, FakeClient)
    assert client1.uri == "mongodb://unit-test:27017"
    assert client1.kwargs["maxPoolSize"] == 123
    assert client1.kwargs["serverSelectionTimeoutMS"] == 1111
    assert client1.kwargs["connectTimeoutMS"] == 2222
    assert client1.kwargs["socketTimeoutMS"] == 3333


async def test_get_db_returns_database_from_client(monkeypatch):
    import app.common.database as db

    # Arrange: force singleton to our FakeClient
    fake = FakeClient("mongodb://ignored")
    monkeypatch.setattr(db, "_client_singleton", fake, raising=False)

    settings = types.SimpleNamespace(MONGODB_DATABASE="chatbot_async")
    database = await db.get_db(settings)

    assert database == {"db": "chatbot_async"}


async def test_ping_db_success(monkeypatch):
    import app.common.database as db

    # Provide a FakeClient via get_mongo_client
    fake = FakeClient("mongodb://ignored")
    monkeypatch.setattr(db, "get_mongo_client", lambda s=None: fake)

    ok = await db.ping_db()
    assert ok is True


async def test_ping_db_retries_and_succeeds(monkeypatch):
    import app.common.database as db

    class FlakyAdmin(FakeClient.Admin):
        def __init__(self, fail_times=2):
            super().__init__()
            self.fail_times = fail_times

        async def command(self, name):
            self.calls += 1
            if self.calls <= self.fail_times:
                raise RuntimeError("temporary failure")
            return {"ok": 1}

    class FlakyClient(FakeClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.admin = FlakyAdmin()

    fake = FlakyClient("mongodb://ignored")

    monkeypatch.setattr(db, "get_mongo_client", lambda s=None: fake)
    # Speed up backoff sleeps - create a proper async function that returns immediately
    async def mock_sleep(*args, **kwargs):
        pass
    
    monkeypatch.setattr(db.asyncio, "sleep", mock_sleep)

    ok = await db.ping_db(retries=3)
    assert ok is True


async def test_ping_db_fails_after_retries(monkeypatch):
    import app.common.database as db

    class AlwaysFailAdmin(FakeClient.Admin):
        async def command(self, name):
            raise RuntimeError("down")

    class AlwaysFailClient(FakeClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.admin = AlwaysFailAdmin()

    fake = AlwaysFailClient("mongodb://ignored")

    monkeypatch.setattr(db, "get_mongo_client", lambda s=None: fake)
    # Speed up backoff sleeps - create a proper async function that returns immediately
    async def mock_sleep(*args, **kwargs):
        pass
    
    monkeypatch.setattr(db.asyncio, "sleep", mock_sleep)

    ok = await db.ping_db(retries=2)
    assert ok is False