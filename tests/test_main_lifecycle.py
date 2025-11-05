import pytest
import asyncio
from types import SimpleNamespace

import app.main as main


class DummyApp:
    pass


@pytest.mark.asyncio
async def test_lifespan_calls_startup_and_shutdown(monkeypatch):
    called = {
        "init_database": False,
        "init_dialogue_manager": False,
        "close_database": False,
    }

    async def fake_init_dialogue_manager(db):
        called["init_dialogue_manager"] = True

    async def fake_init_database(settings=None):
        called["init_database"] = True
        return "fake_db"

    async def fake_close_database():
        called["close_database"] = True

    monkeypatch.setattr(main, "init_database", fake_init_database)
    monkeypatch.setattr(main, "init_dialogue_manager", fake_init_dialogue_manager)
    monkeypatch.setattr(main, "close_database", fake_close_database)

    # Use the lifespan async context manager
    async with main.lifespan(DummyApp()) as resource:
        # inside context - startup should have run
        assert called["init_database"] is True
        assert called["init_dialogue_manager"] is True
        # The lifespan context should yield a resource (like db, dialogue_manager tuple or similar)
        # Assert it yields a tuple
        assert isinstance(resource, tuple)
        # Assert it is a tuple of length 2
        assert len(resource) == 2

    # after exiting, shutdown helpers should be invoked
    assert called["close_database"] is True