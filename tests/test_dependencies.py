import pytest
import asyncio
from types import SimpleNamespace

import app.dependencies as deps


class FakeDM:
    def __init__(self):
        self.updated = False

    async def update_model(self, models_dir):
        self.updated = True


@pytest.mark.asyncio
async def test_init_dialogue_manager_sets_global(monkeypatch):
    fake_settings = SimpleNamespace(MODELS_DIR='/tmp', DEFAULT_FALLBACK_INTENT_NAME='fallback')

    async def fake_from_config(database=None):
        dm = FakeDM()
        await dm.update_model(fake_settings.MODELS_DIR)
        return dm

    def fake_init_database(settings):
        # noop
        pass

    monkeypatch.setattr(deps, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(deps, "init_database", fake_init_database)
    monkeypatch.setattr(deps, "DialogueManager", None)
    # patch the classmethod on the DialogueManager import path inside dependencies
    monkeypatch.setattr('app.dependencies.DialogueManager', SimpleNamespace(from_config=fake_from_config))

    # ensure starting state is None
    await deps.set_dialogue_manager(None)
    await deps.init_dialogue_manager()

    dm = await deps.get_dialogue_manager()
    assert dm is not None
    assert getattr(dm, 'updated', False) is True


@pytest.mark.asyncio
async def test_reload_dialogue_manager(monkeypatch):
    fake_settings = SimpleNamespace(MODELS_DIR='/tmp')

    async def fake_from_config(database=None):
        dm = FakeDM()
        await dm.update_model(fake_settings.MODELS_DIR)
        return dm

    monkeypatch.setattr(deps, "get_settings", lambda: fake_settings)
    monkeypatch.setattr('app.dependencies.DialogueManager', SimpleNamespace(from_config=fake_from_config))

    # call reload
    await deps.reload_dialogue_manager()
    dm = await deps.get_dialogue_manager()
    assert dm is not None
    assert getattr(dm, 'updated', False) is True