import pytest
from app.bot.memory.memory_saver_mongo import MemorySaverMongo


class DummyDB:
    def get_collection(self, name):
        return object()


class DummyClient:
    def __init__(self):
        self.db = DummyDB()

    def get_database(self, name):
        return self.db


def test_accepts_database_instance():
    ms = MemorySaverMongo(DummyDB())
    assert hasattr(ms, "db") and hasattr(ms, "collection")


def test_accepts_client_instance_and_dbname():
    ms = MemorySaverMongo(DummyClient(), db_name="custom")
    assert hasattr(ms, "db") and hasattr(ms, "collection")


def test_rejects_invalid_type():
    with pytest.raises(TypeError):
        MemorySaverMongo(object())