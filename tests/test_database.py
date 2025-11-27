import asyncio
import pytest
from typing import get_origin, get_args
from bson import ObjectId

import app.database as dbmodule
from app.database import DatabaseClient


@pytest.mark.asyncio
async def test_objectidfield_is_annotated_correctly() -> None:
    """ObjectIdField should be an Annotated type with ObjectId as origin and two metadata items."""
    # For Annotated types, get_origin returns typing.Annotated
    # The actual type is the first argument in get_args()
    args = get_args(dbmodule.ObjectIdField)
    origin = args[0]  # First argument is the actual type (ObjectId)
    assert origin is ObjectId
    metadata = args[1:]  # Remaining arguments are metadata
    # Expect two metadata entries: serializer and validator
    assert len(metadata) == 2


class FakeDB:
    def __init__(self, should_raise: bool = False):
        self._should_raise = should_raise
        self.command_called = False

    async def command(self, cmd: str):
        self.command_called = True
        if self._should_raise:
            raise RuntimeError("db command failed")
        return {"ok": 1}


class FakeClient:
    def __init__(self, host: str = "", **kwargs):
        self.host = host
        self.kwargs = kwargs
        self.closed = False
        self._db = FakeDB()

    def get_database(self, name: str):
        return self._db

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_connect_success(monkeypatch) -> None:
    """connect() should initialize client and database on successful connection."""
    # Patch the AsyncIOMotorClient used in the module to our FakeClient
    monkeypatch.setattr(dbmodule, "AsyncIOMotorClient", FakeClient)

    client = DatabaseClient("mongodb://localhost:27017", "testdb")
    await client.connect()

    assert isinstance(client._client, FakeClient)
    assert client._database is client._client.get_database("testdb")
    # properties should return without error
    assert client.client is client._client
    assert client.database is client._database


@pytest.mark.asyncio
async def test_connect_retries_then_succeeds(monkeypatch) -> None:
    """connect() should retry if AsyncIOMotorClient raises initially and succeed afterwards."""
    call_count = {"n": 0}

    class FlakyFactory:
        def __init__(self, host: str = "", **kwargs):
            call_count["n"] += 1
            # Fail first two attempts, succeed on third
            if call_count["n"] < 3:
                raise RuntimeError("connection failed")
            # otherwise behave like FakeClient
            self._inner = FakeClient(host, **kwargs)

        def get_database(self, name: str):
            return self._inner.get_database(name)

        def close(self):
            return self._inner.close()

    monkeypatch.setattr(dbmodule, "AsyncIOMotorClient", FlakyFactory)

    client = DatabaseClient(
        "mongodb://localhost:27017",
        "testdb",
        retry_attempts=4,
        retry_delay_ms=1,
    )

    await client.connect()
    assert call_count["n"] >= 3
    assert isinstance(client._client, FlakyFactory)
    assert client._database is client._client.get_database("testdb")


@pytest.mark.asyncio
async def test_connect_fails_after_retries(monkeypatch) -> None:
    """connect() should raise if all retry attempts fail."""
    call_count = {"n": 0}

    class AlwaysFail:
        def __init__(self, host: str = "", **kwargs):
            call_count["n"] += 1
            raise RuntimeError("always fails")

    monkeypatch.setattr(dbmodule, "AsyncIOMotorClient", AlwaysFail)

    client = DatabaseClient(
        "mongodb://localhost:27017",
        "testdb",
        retry_attempts=3,
        retry_delay_ms=1,
    )

    with pytest.raises(RuntimeError):
        await client.connect()

    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_disconnect_closes_client(monkeypatch) -> None:
    """disconnect() should call close() on the underlying client if present."""
    client = DatabaseClient("host", "db")
    fake = FakeClient()
    client._client = fake

    await client.disconnect()
    assert fake.closed is True


@pytest.mark.asyncio
async def test_disconnect_no_client_does_not_raise() -> None:
    """disconnect() should be a no-op if no client is present."""
    client = DatabaseClient("host", "db")
    # no client set
    await client.disconnect()  # should not raise


@pytest.mark.asyncio
async def test_health_check_not_initialized() -> None:
    """health_check() should return False when database is not initialized."""
    client = DatabaseClient("host", "db")
    assert await client.health_check() is False


@pytest.mark.asyncio
async def test_health_check_success(monkeypatch) -> None:
    """health_check() should return True when the database responds to ping."""
    client = DatabaseClient("host", "db")
    fake_db = FakeDB(should_raise=False)
    client._database = fake_db

    assert await client.health_check() is True
    assert fake_db.command_called is True


@pytest.mark.asyncio
async def test_health_check_failure_on_command(monkeypatch) -> None:
    """health_check() should return False when the database command raises an exception."""
    client = DatabaseClient("host", "db")
    fake_db = FakeDB(should_raise=True)
    client._database = fake_db

    assert await client.health_check() is False
    assert fake_db.command_called is True


def test_client_property_raises_if_not_initialized() -> None:
    """Accessing .client before connect() should raise RuntimeError."""
    client = DatabaseClient("host", "db")
    with pytest.raises(RuntimeError):
        _ = client.client


def test_database_property_raises_if_not_initialized() -> None:
    """Accessing .database before connect() should raise RuntimeError."""
    client = DatabaseClient("host", "db")
    with pytest.raises(RuntimeError):
        _ = client.database


@pytest.mark.asyncio
async def test_get_database_client_and_get_database_helpers(monkeypatch) -> None:
    """Module-level helpers should return the module _db_client and its database property."""
    fake_db_obj = object()

    class DummyDBClient:
        def __init__(self, dbobj):
            self._dbobj = dbobj

        @property
        def database(self):
            return self._dbobj

    dummy = DummyDBClient(fake_db_obj)
    # patch the module-level _db_client
    monkeypatch.setattr(dbmodule, "_db_client", dummy)

    got_client = await dbmodule.get_database_client()
    assert got_client is dummy

    got_db = await dbmodule.get_database()
    assert got_db is fake_db_obj