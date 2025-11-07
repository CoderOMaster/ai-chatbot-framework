import importlib
import sys
import types


def test_database_uses_settings_and_client(monkeypatch):
    class DummySettings:
        MONGODB_HOST = "mongodb://example:27017"
        MONGODB_DATABASE = "testdb"

    class DummyDB:
        def __init__(self, name):
            self.name = name

    class DummyClient:
        def __init__(self, host):
            self.host = host

        def get_database(self, name):
            self.dbname = name
            return DummyDB(name)

    # ensure a clean import
    sys.modules.pop("app.database", None)
    monkeypatch.setitem(
        sys.modules,
        "ai_chatbot_common.config",
        types.SimpleNamespace(get_settings=lambda: DummySettings()),
    )
    monkeypatch.setitem(
        sys.modules,
        "motor.motor_asyncio",
        types.SimpleNamespace(AsyncIOMotorClient=DummyClient),
    )

    import app.database as db

    assert isinstance(db.client, DummyClient)
    assert db.client.host == "mongodb://example:27017"
    assert db.database.name == "testdb"