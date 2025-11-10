import pytest

import app.dependencies as deps


class DummyDM:
    instance_counter = 0

    def __init__(self):
        self.id = DummyDM.instance_counter
        DummyDM.instance_counter += 1

    @classmethod
    async def from_config(cls):
        return cls()


@pytest.mark.asyncio
async def test_init_dialogue_manager_sets_global(monkeypatch):
    # Patch DialogueManager used inside dependencies module
    monkeypatch.setattr(deps, "DialogueManager", DummyDM, raising=True)

    # Ensure clean state
    await deps.set_dialogue_manager(None)

    await deps.init_dialogue_manager()
    dm = await deps.get_dialogue_manager()
    assert isinstance(dm, DummyDM)


@pytest.mark.asyncio
async def test_reload_dialogue_manager_replaces_instance(monkeypatch):
    monkeypatch.setattr(deps, "DialogueManager", DummyDM, raising=True)

    await deps.init_dialogue_manager()
    first = await deps.get_dialogue_manager()

    await deps.reload_dialogue_manager()
    second = await deps.get_dialogue_manager()

    assert isinstance(first, DummyDM) and isinstance(second, DummyDM)
    assert first is not second
    assert first.id != second.id


@pytest.mark.asyncio
async def test_set_and_get_dialogue_manager_none():
    await deps.set_dialogue_manager(None)
    dm = await deps.get_dialogue_manager()
    assert dm is None