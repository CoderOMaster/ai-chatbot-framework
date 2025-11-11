import pytest
from app.bot.memory.models import State
from app.bot.memory.memory_saver_mongo import MemorySaverMongo

pytestmark = pytest.mark.asyncio


class FakeCursor:
    def __init__(self, items):
        self._items = items

    async def to_list(self, length=None):
        return list(self._items)


class FakeCollection:
    def __init__(self, items=None):
        self.items = items or []
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(doc)
        self.items.append(doc)
        return {"inserted_id": "fake"}

    async def find_one(self, *args, **kwargs):
        # Return the most recent matching (simulate sort by natural -1)
        for doc in reversed(self.items):
            return doc
        return None

    def find(self, *args, **kwargs):
        # Return in reverse to simulate natural -1
        return FakeCursor(list(reversed(self.items)))


class FakeDB:
    def __init__(self, items=None):
        self._collection = FakeCollection(items)

    def get_collection(self, name):
        return self._collection


async def test_memory_saver_mongo_save_inserts_state():
    db = FakeDB()
    saver = MemorySaverMongo(db)

    st = State(thread_id="t1", context={"foo": "bar"}, current_node="n1")
    await saver.save("t1", st)

    assert db._collection.inserted, "Expected insert_one to be called"
    assert db._collection.inserted[0]["thread_id"] == "t1"
    assert db._collection.inserted[0]["context"]["foo"] == "bar"


async def test_memory_saver_mongo_get_returns_state():
    seed = {
        "thread_id": "t1",
        "context": {"x": 1},
        "intent": {"id": "i1"},
        "parameters": [],
        "extracted_parameters": {},
        "missing_parameters": [],
        "complete": False,
        "current_node": "root",
    }
    db = FakeDB(items=[seed])
    saver = MemorySaverMongo(db)

    state = await saver.get("t1")
    assert isinstance(state, State)
    assert state.thread_id == "t1"
    assert state.context == {"x": 1}
    assert state.get_active_intent_id() == "i1"


async def test_memory_saver_mongo_get_all_returns_list_of_states():
    seeds = [
        {
            "thread_id": "t1",
            "context": {"i": 1},
            "intent": {},
            "parameters": [],
            "extracted_parameters": {},
            "missing_parameters": [],
            "complete": False,
            "current_node": "a",
        },
        {
            "thread_id": "t1",
            "context": {"i": 2},
            "intent": {},
            "parameters": [],
            "extracted_parameters": {},
            "missing_parameters": [],
            "complete": False,
            "current_node": "b",
        },
    ]

    db = FakeDB(items=seeds)
    saver = MemorySaverMongo(db)

    states = await saver.get_all("t1")
    assert isinstance(states, list)
    assert len(states) == 2
    # Order should be natural -1 (most recent first)
    assert states[0].context == {"i": 2}
    assert states[1].context == {"i": 1}