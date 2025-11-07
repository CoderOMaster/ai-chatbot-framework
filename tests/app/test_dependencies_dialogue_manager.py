import pytest
from app import dependencies as deps


class FakeDM:
    def __init__(self):
        self.updated_with = None

    @classmethod
    async def from_config(cls):
        return cls()

    def update_model(self, models_dir):
        self.updated_with = models_dir


class DummySettings:
    MODELS_DIR = "/tmp/models"


@pytest.mark.asyncio
async def test_init_dialogue_manager(monkeypatch):
    monkeypatch.setattr("app.dependencies.DialogueManager", FakeDM)
    monkeypatch.setattr("app.dependencies.get_settings", lambda: DummySettings())
    await deps.init_dialogue_manager()
    dm = await deps.get_dialogue_manager()
    assert isinstance(dm, FakeDM)
    assert dm.updated_with == "/tmp/models"


@pytest.mark.asyncio
async def test_reload_dialogue_manager(monkeypatch):
    monkeypatch.setattr("app.dependencies.DialogueManager", FakeDM)
    monkeypatch.setattr("app.dependencies.get_settings", lambda: DummySettings())
    await deps.init_dialogue_manager()
    first = await deps.get_dialogue_manager()
    await deps.reload_dialogue_manager()
    second = await deps.get_dialogue_manager()
    assert second is not first
    assert isinstance(second, FakeDM)