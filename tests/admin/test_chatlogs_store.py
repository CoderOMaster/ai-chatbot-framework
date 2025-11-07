import pytest
from datetime import datetime, timedelta


class FakeAggregate:
    def __init__(self, docs):
        # list of docs to yield
        self._docs = list(docs)

    async def to_list(self, length):
        # for count pipeline usage
        return list(self._docs[:length]) if length is not None else list(self._docs)

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *args, **kwargs):
        # already sorted for test simplicity
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, aggregate_responses=None, find_docs=None):
        self._aggregate_responses = list(aggregate_responses or [])
        self._find_docs = list(find_docs or [])

    def aggregate(self, pipeline):
        # Pop next prepared response
        docs = self._aggregate_responses.pop(0) if self._aggregate_responses else []
        return FakeAggregate(docs)

    def find(self, filt):
        return FakeCursor(self._find_docs)


@pytest.mark.asyncio
async def test_list_chatlogs_groups_and_paginates(monkeypatch):
    from app.admin.chatlogs import store

    now = datetime.utcnow()
    grouped_docs = [
        {"thread_id": "t1", "date": now},
        {"thread_id": "t2", "date": now - timedelta(minutes=1)},
    ]
    total_count = [{"total": 5}]  # pretend there are 5 unique threads overall

    fake_collection = FakeCollection(aggregate_responses=[total_count, grouped_docs])
    monkeypatch.setattr(store, "collection", fake_collection)

    resp = await store.list_chatlogs(page=1, limit=2)
    assert resp.total == 5
    assert resp.page == 1 and resp.limit == 2
    assert [c.thread_id for c in resp.conversations] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_get_chat_thread_returns_logs(monkeypatch):
    from app.admin.chatlogs import store

    msgs = [
        {
            "user_message": {"text": "hi"},
            "bot_message": [{"text": "hello"}],
            "date": datetime.utcnow(),
            "context": {"k": "v"},
        },
        {
            "user_message": {"text": "bye"},
            "bot_message": [{"text": "goodbye"}],
            "date": datetime.utcnow(),
            "context": {},
        },
    ]

    fake_collection = FakeCollection(find_docs=msgs)
    monkeypatch.setattr(store, "collection", fake_collection)

    logs = await store.get_chat_thread("tid")
    assert isinstance(logs, list)
    assert len(logs) == 2
    assert logs[0].user_message.text == "hi"
    assert logs[0].bot_message[0].text == "hello"


@pytest.mark.asyncio
async def test_get_chat_thread_none_when_empty(monkeypatch):
    from app.admin.chatlogs import store

    fake_collection = FakeCollection(find_docs=[])
    monkeypatch.setattr(store, "collection", fake_collection)

    logs = await store.get_chat_thread("tid")
    assert logs is None