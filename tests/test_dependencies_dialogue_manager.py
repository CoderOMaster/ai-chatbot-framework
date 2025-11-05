import asyncio
import pytest

import app.dependencies as deps


class DummyDialogueManager:
    def __init__(self):
        self.updated_model = None

    async def update_model(self, path):
        # simulate async update
        self.updated_model = path

    @classmethod
    async def from_config(cls):
        # simulate async construction
        await asyncio.sleep(0)
        return cls()


@pytest.mark.asyncio
async def test_get_set_dialogue_manager():
    # Reset private variable
    deps._dialogue_manager = None

    dm = await deps.get_dialogue_manager()
    assert dm is None

    dummy = DummyDialogueManager()

    await deps.set_dialogue_manager(dummy)
    dm2 = await deps.get_dialogue_manager()
    assert dm2 is dummy


@pytest.mark.asyncio
async def test_init_and_reload_dialogue_manager(monkeypatch):
    # Monkeypatch DialogueManager to our dummy implementation
    import app.bot.dialogue_manager.dialogue_manager as dm_mod

    async def dummy_from_config():
        dm = await DummyDialogueManager.from_config()
        await dm.update_model("test_models")
        return dm

    monkeypatch.setattr(dm_mod.DialogueManager, "from_config", staticmethod(dummy_from_config))

    # Also ensure Settings.MODELS_DIR is used
    import app.common.config as config_mod
    config_mod._settings_singleton = None
    s = config_mod.get_settings()
    s.MODELS_DIR = "test_models"

    # Run init
    await deps.init_dialogue_manager()
    dm = await deps.get_dialogue_manager()
    assert dm is not None
    # our DummyDialogueManager should have update_model called with test_models
    assert getattr(dm, "updated_model", None) == "test_models"

    # Test reload replaces the object
    old_dm = dm
    await deps.reload_dialogue_manager()
    new_dm = await deps.get_dialogue_manager()
    assert new_dm is not None
    assert new_dm is not old_dm
    assert getattr(new_dm, "updated_model", None) == "test_models"