import pytest
from types import SimpleNamespace

from app.database import (
    CollectionGetter,
    create_collection_getter_from_config,
    create_mongo_collection_getter,
)


class FakeDatabase:
    """A fake in-memory database that records accessed collections."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.accessed_collections: list[str] = []

    def __getitem__(self, collection_name: str) -> str:
        self.accessed_collections.append(collection_name)
        return f"{self.name}:{collection_name}"


class FakeClient:
    """A fake motor client that lazily creates fake databases."""

    instances: list["FakeClient"] = []

    def __init__(self, host: str) -> None:
        self.host = host
        type(self).instances.append(self)
        self.databases: dict[str, FakeDatabase] = {}
        self.get_database_calls: list[str] = []

    def get_database(self, name: str) -> FakeDatabase:
        self.get_database_calls.append(name)
        if name not in self.databases:
            self.databases[name] = FakeDatabase(name)
        return self.databases[name]


@pytest.fixture(autouse=True)
def reset_fake_client_instances() -> None:
    """Ensure FakeClient state is reset between tests."""

    FakeClient.instances.clear()
    yield
    FakeClient.instances.clear()


@pytest.fixture
def patched_motor_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch AsyncIOMotorClient in the module under test with the fake client."""

    monkeypatch.setattr("app.database.AsyncIOMotorClient", FakeClient)


def test_create_mongo_collection_getter_returns_collection(
    patched_motor_client: None,
) -> None:
    """The getter should return named collections from the configured database."""

    host = "mongodb://example"
    database_name = "products"
    getter: CollectionGetter = create_mongo_collection_getter(host, database_name)

    collection = getter("inventory")

    assert collection == "products:inventory"
    assert len(FakeClient.instances) == 1
    client = FakeClient.instances[0]
    assert client.host == host
    assert client.get_database_calls == [database_name]
    assert list(client.databases[database_name].accessed_collections) == ["inventory"]


def test_create_mongo_collection_getter_reuses_client_and_database(
    patched_motor_client: None,
) -> None:
    """Repeated lookups should reuse the existing client and database instances."""

    getter: CollectionGetter = create_mongo_collection_getter(
        "mongodb://example", "analytics"
    )

    first = getter("events")
    second = getter("sessions")

    assert first == "analytics:events"
    assert second == "analytics:sessions"

    assert len(FakeClient.instances) == 1
    client = FakeClient.instances[0]
    assert client.get_database_calls == ["analytics"]
    assert list(client.databases["analytics"].accessed_collections) == ["events", "sessions"]


def test_create_collection_getter_from_config_uses_config_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory should use AppConfig attributes when delegating to the low-level helper."""

    recorded: dict[str, str] = {}

    def fake_creator(host: str, database_name: str) -> CollectionGetter:
        recorded["host"] = host
        recorded["database_name"] = database_name

        def getter(_: str) -> str:
            return "stub"

        return getter

    monkeypatch.setattr("app.database.create_mongo_collection_getter", fake_creator)

    config = SimpleNamespace(MONGODB_HOST="mongo-host", MONGODB_DATABASE="config-db")
    getter = create_collection_getter_from_config(config)

    assert callable(getter)
    assert recorded == {"host": "mongo-host", "database_name": "config-db"}
    assert getter("anything") == "stub"