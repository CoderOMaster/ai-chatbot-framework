import pytest
from app.bot.memory.memory_saver_mongo import MemorySaverMongo
from app.bot.memory.models import State


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def find_one(self, filt, projection, sort):
        for doc in reversed(self.docs):
            if doc.get("thread_id") == filt.get("thread_id"):
                result = dict(doc)
                for k, v in projection.items():
                    if v == 0 and k in result:
                        result.pop(k, None)
                return result
        return None

    def find(self, filt, sort):
        matched = [d for d in self.docs if d.get("thread_id") == filt.get("thread_id")]
        return FakeCursor(matched)


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self):
        return list(self.docs)


class FakeDB:
    def __init__(self):
        self.collections = {}

    def get_collection(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


class FakeClient:
    def __init__(self):
        self.db = FakeDB()

    def get_database(self, name):
        return self.db


@pytest.mark.asyncio
async def test_save_and_get_roundtrip(monkeypatch):
    client = FakeClient()
    ms = MemorySaverMongo(client)
    state = State(thread_id="tid")
    await ms.save("tid", state)
    loaded = await ms.get("tid")
    assert isinstance(loaded, State)
    assert loaded.thread_id == "tid"
    # ensure stripped fields are indeed not persisted
    assert loaded.user_message is None
    assert loaded.context == {}


@pytest.mark.asyncio
async def test_get_all(monkeypatch):
    client = FakeClient()
    ms = MemorySaverMongo(client)
    await ms.save("tid", State(thread_id="tid", context={"x": 1}))
    await ms.save("tid", State(thread_id="tid", context={"y": 2}))
    results = await ms.get_all("tid")
    assert len(results) == 2
    assert all(isinstance(r, State) for r in results)