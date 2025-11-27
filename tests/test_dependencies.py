import asyncio
import pytest
from types import SimpleNamespace

import app.dependencies as dependencies

pytest_plugins = "pytest_asyncio"


@pytest.fixture(autouse=True)
def fresh_container():
    """Ensure each test gets a fresh DialogueManagerContainer instance."""
    dependencies._container = dependencies.DialogueManagerContainer()
    yield


class FakeMemorySaver:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeDialogueManager:
    """A fake dialogue manager to emulate the real one used by the container."""

    def __init__(self, name="mgr", nlu_pipeline=True, cleanup_raises=False):
        self.name = name
        self.nlu_pipeline = nlu_pipeline
        self.cleaned = False
        self.cleanup_raises = cleanup_raises
        self.memory_saver = FakeMemorySaver()
        self.updated_model_path = None

    @classmethod
    async def from_config(cls):
        # Emulate async construction from config
        await asyncio.sleep(0)
        return cls()

    def update_model(self, models_dir):
        # record that update_model was called with given path
        self.updated_model_path = models_dir

    async def cleanup(self):
        await asyncio.sleep(0)
        if self.cleanup_raises:
            raise RuntimeError("cleanup failed")
        self.cleaned = True


@pytest.mark.asyncio
async def test_get_before_init_raises():
    """get() should raise when DialogueManager isn't initialized."""
    with pytest.raises(RuntimeError, match="not initialized"):
        await dependencies._container.get()


@pytest.mark.asyncio
async def test_init_success(monkeypatch):
    """init() should create a manager and call update_model with CONFIG path."""
    # monkeypatch DialogueManager.from_config to return our fake instance
    async def fake_from_config():
        await asyncio.sleep(0)
        return FakeDialogueManager()

    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=fake_from_config))
    # set app_config.MODELS_DIR
    monkeypatch.setattr(dependencies.app_config, "MODELS_DIR", "/models/path")

    await dependencies._container.init()
    mgr = await dependencies._container.get()
    assert isinstance(mgr, FakeDialogueManager)
    assert mgr.updated_model_path == "/models/path"


@pytest.mark.asyncio
async def test_init_already_initialized_raises(monkeypatch):
    """Calling init twice should raise a RuntimeError on second call."""
    async def fake_from_config():
        return FakeDialogueManager()

    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=fake_from_config))
    monkeypatch.setattr(dependencies.app_config, "MODELS_DIR", "/models/path")

    await dependencies._container.init()
    with pytest.raises(RuntimeError, match="already initialized"):
        await dependencies._container.init()


@pytest.mark.asyncio
async def test_init_failure_propagates(monkeypatch):
    """If DialogueManager.from_config raises, init should propagate the exception."""
    async def bad_from_config():
        raise RuntimeError("failed to create")

    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=bad_from_config))
    with pytest.raises(RuntimeError, match="failed to create"):
        await dependencies._container.init()


@pytest.mark.asyncio
async def test_reload_swaps_and_cleans_old_manager(monkeypatch):
    """reload() should atomically swap managers and cleanup the old one if cleanup exists."""
    # First manager
    old = FakeDialogueManager(name="old")

    async def first_from_config():
        return old

    async def second_from_config():
        return FakeDialogueManager(name="new")

    # set up so first init uses first_from_config
    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=first_from_config))
    monkeypatch.setattr(dependencies.app_config, "MODELS_DIR", "/m")
    await dependencies._container.init()

    # Replace DialogueManager.from_config to create a different instance for reload
    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=second_from_config))

    await dependencies._container.reload()

    mgr = await dependencies._container.get()
    assert mgr.name == "new"
    # old cleanup should have been called
    assert old.cleaned is True


@pytest.mark.asyncio
async def test_reload_handles_old_cleanup_exception(monkeypatch):
    """If old manager.cleanup raises, reload should still succeed and not propagate cleanup error."""
    old = FakeDialogueManager(name="old", cleanup_raises=True)

    async def first_from_config():
        return old

    async def second_from_config():
        return FakeDialogueManager(name="new")

    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=first_from_config))
    monkeypatch.setattr(dependencies.app_config, "MODELS_DIR", "/m")
    await dependencies._container.init()

    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=second_from_config))

    # Should not raise even though cleanup raises
    await dependencies._container.reload()
    mgr = await dependencies._container.get()
    assert mgr.name == "new"


@pytest.mark.asyncio
async def test_reload_without_init_raises():
    """Calling reload when not initialized should raise RuntimeError."""
    with pytest.raises(RuntimeError, match="not initialized"):
        await dependencies._container.reload()


@pytest.mark.asyncio
async def test_shutdown_cleans_and_closes_memory_saver(monkeypatch):
    """shutdown() should call cleanup and close memory_saver then set manager to None."""
    async def fake_from_config():
        return FakeDialogueManager(name="to_shutdown")

    monkeypatch.setattr(dependencies, "DialogueManager", SimpleNamespace(from_config=fake_from_config))
    monkeypatch.setattr(dependencies.app_config, "MODELS_DIR", "/m")

    await dependencies._container.init()
    mgr = await dependencies._container.get()
    assert mgr.cleaned is False
    assert mgr.memory_saver.closed is False

    await dependencies._container.shutdown()
    # manager should be None after shutdown
    assert dependencies._container._dialogue_manager is None
    # cleanup and close should have run
    assert mgr.cleaned is True
    assert mgr.memory_saver.closed is True


@pytest.mark.asyncio
async def test_shutdown_when_no_manager_logs_and_returns(monkeypatch):
    """shutdown() should be a no-op when no manager exists (no exception raised)."""
    # Ensure no manager present
    dependencies._container._dialogue_manager = None
    await dependencies._container.shutdown()
    assert dependencies._container._dialogue_manager is None


@pytest.mark.asyncio
async def test_health_check_various_states(monkeypatch):
    """health_check should report correct statuses for different container states."""
    # 1) Not initialized
    h = await dependencies._container.health_check()
    assert h["status"] == "unhealthy"
    assert h["error"] == "DialogueManager not initialized"

    # 2) Initialized but nlu_pipeline None
    m = FakeDialogueManager()
    m.nlu_pipeline = None
    dependencies._container._dialogue_manager = m
    h = await dependencies._container.health_check()
    assert h["status"] == "unhealthy"
    assert "NLU pipeline" in h["error"]

    # 3) Healthy
    m.nlu_pipeline = True
    h = await dependencies._container.health_check()
    assert h["status"] == "healthy"

    # 4) Shutting down
    dependencies._container._is_shutting_down = True
    h = await dependencies._container.health_check()
    assert h["status"] == "unhealthy"
    assert h["shutting_down"] is True


@pytest.mark.asyncio
async def test_get_while_shutting_down_raises(monkeypatch):
    """get() should raise if shutdown is in progress."""
    m = FakeDialogueManager()
    dependencies._container._dialogue_manager = m
    dependencies._container._is_shutting_down = True
    with pytest.raises(RuntimeError, match="shutting down"):
        await dependencies._container.get()


@pytest.mark.asyncio
async def test_top_level_helpers_delegate(monkeypatch):
    """Top-level functions should delegate to the container instance methods."""
    called = {}

    async def fake_init():
        called['init'] = True

    async def fake_reload():
        called['reload'] = True

    async def fake_shutdown():
        called['shutdown'] = True

    async def fake_health():
        called['health'] = True
        return {"status": "ok"}

    # Replace the global container with an object providing the methods
    fake_container = SimpleNamespace(
        init=fake_init,
        reload=fake_reload,
        shutdown=fake_shutdown,
        health_check=fake_health,
        get=lambda: "dummy",  # won't be awaited in this test
    )
    dependencies._container = fake_container

    await dependencies.init_dialogue_manager()
    await dependencies.reload_dialogue_manager()
    await dependencies.shutdown_dialogue_manager()
    res = await dependencies.health_check_dialogue_manager()

    assert called['init'] is True
    assert called['reload'] is True
    assert called['shutdown'] is True
    assert called['health'] is True
    assert res == {"status": "ok"}


@pytest.mark.asyncio
async def test_lifespan_manager_calls_init_and_shutdown(monkeypatch):
    """The lifespan_manager context should call init_dialogue_manager on enter and shutdown_dialogue_manager on exit."""
    flags = {}

    async def fake_init():
        flags['started'] = True

    async def fake_shutdown():
        flags['stopped'] = True

    monkeypatch.setattr(dependencies, 'init_dialogue_manager', fake_init)
    monkeypatch.setattr(dependencies, 'shutdown_dialogue_manager', fake_shutdown)

    async with dependencies.lifespan_manager():
        assert flags.get('started') is True
        # inside context
        assert flags.get('stopped') is None

    # after context manager exit
    assert flags.get('stopped') is True