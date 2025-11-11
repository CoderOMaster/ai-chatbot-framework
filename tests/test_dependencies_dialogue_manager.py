import asyncio
import types
import pytest

from app.dependencies import (
    get_dialogue_manager,
    set_dialogue_manager,
    init_dialogue_manager,
    reload_dialogue_manager,
)


class DummyDialogueManager:
    def __init__(self):
        self.updated_with = None

    @classmethod
    async def from_config(cls):
        await asyncio.sleep(0)
        return cls()

    def update_model(self, path):
        self.updated_with = path


@pytest.fixture(autouse=True)
async def patch_dialogue_manager(monkeypatch):
    # Patch the DialogueManager used in dependencies to our dummy
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.bot.dialogue_manager.dialogue_manager",
        types.SimpleNamespace(DialogueManager=DummyDialogueManager),
    )
    # Also ensure MODELS_DIR is deterministic
    from app.common.config import Settings
    monkeypatch.setenv("MODELS_DIR", "test-models")
    yield


@pytest.mark.asyncio
async def test_get_set_dialogue_manager_roundtrip():
    assert await get_dialogue_manager() is None
    dm = DummyDialogueManager()
    await set_dialogue_manager(dm)
    assert await get_dialogue_manager() is dm


@pytest.mark.asyncio
async def test_init_dialogue_manager_creates_and_updates_with_models_dir(monkeypatch):
    await init_dialogue_manager()
    dm = await get_dialogue_manager()
    assert isinstance(dm, DummyDialogueManager)
    assert dm.updated_with == "test-models"


@pytest.mark.asyncio
async def test_reload_dialogue_manager_replaces_global(monkeypatch):
    dm1 = DummyDialogueManager()
    await set_dialogue_manager(dm1)
    await reload_dialogue_manager()
    dm2 = await get_dialogue_manager()
    assert isinstance(dm2, DummyDialogueManager)
    assert dm2 is not dm1
    assert dm2.updated_with == "test-models"