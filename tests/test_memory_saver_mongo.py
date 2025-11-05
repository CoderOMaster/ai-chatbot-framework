import pytest
from types import SimpleNamespace

import app.bot.memory.memory_saver_mongo as msm
import app.bot.memory.models as models


class FakeCollection:
    def __init__(self):
        self.inserted = None

    async def insert_one(self, doc):
        self.inserted = doc

    async def find_one(self, *args, **kwargs):
        return {"thread_id": "t1", "some": "data"}

    def find(self, *args, **kwargs):
        class Cursor:
            def __init__(self):
                pass

            async def to_list(self):
                return []

        return Cursor()


class FakeDB:
    def get_collection(self, name):
        return FakeCollection()


def test_init_sets_collection():
    db = FakeDB()
    saver = msm.MemorySaverMongo(db)
    assert saver.collection is not None


@pytest.fixture
def saver():
    db = FakeDB()
    return msm.MemorySaverMongo(db)


@pytest.mark.anyio
async def test_save_calls_insert_one(saver):
    state = SimpleNamespace(to_dict=lambda: {"thread_id": "t1"})
    await saver.save('t1', state)
    assert saver.collection.inserted is not None


@pytest.mark.anyio
async def test_get_returns_state(monkeypatch, saver):
    sentinel = object()

    async def fake_find_one(*args, **kwargs):
        return {"thread_id": "t1"}

    monkeypatch.setattr(saver.collection, 'find_one', fake_find_one)

    monkeypatch.setattr('app.bot.memory.memory_saver_mongo.State', SimpleNamespace(from_dict=lambda d: sentinel))

    res = await saver.get('t1')
    assert res is sentinel