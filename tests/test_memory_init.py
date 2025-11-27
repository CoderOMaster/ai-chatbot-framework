import pytest
from dataclasses import FrozenInstanceError
from datetime import datetime

from app.bot.memory import MemorySaver
from app.bot.memory.models import State, StateValidationError


@pytest.fixture
def memory_saver() -> MemorySaver:
    """Fixture returning a fresh MemorySaver instance (interface implementation)."""
    return MemorySaver()


@pytest.mark.asyncio
async def test_init_state_success(memory_saver: MemorySaver):
    """Validate that init_state returns a State with the provided thread_id and default fields set.

    Ensures date is populated, version defaults to 1 and the returned object is an instance of State.
    """
    thread_id = "thread-123"
    state = await memory_saver.init_state(thread_id)

    assert isinstance(state, State)
    assert state.thread_id == thread_id
    assert state.date is not None and isinstance(state.date, datetime)
    assert state.version == 1


@pytest.mark.asyncio
async def test_init_state_empty_thread_raises_validation_error(memory_saver: MemorySaver):
    """Passing an empty thread_id should raise StateValidationError from the State model validation."""
    with pytest.raises(StateValidationError):
        await memory_saver.init_state("")


@pytest.mark.asyncio
async def test_init_state_returns_frozen_state(memory_saver: MemorySaver):
    """The returned State dataclass should be frozen (immutable). Attempting to modify it raises FrozenInstanceError."""
    state = await memory_saver.init_state("thread-x")
    with pytest.raises(FrozenInstanceError):
        state.thread_id = "new-id"


@pytest.mark.asyncio
async def test_save_not_implemented_raises(memory_saver: MemorySaver):
    """The base MemorySaver.save should raise NotImplementedError indicating subclasses must implement it."""
    # create a minimal valid State to pass
    state = State(thread_id="t")
    with pytest.raises(NotImplementedError):
        await memory_saver.save("t", state)


@pytest.mark.asyncio
async def test_get_not_implemented_raises(memory_saver: MemorySaver):
    """The base MemorySaver.get should raise NotImplementedError indicating subclasses must implement it."""
    with pytest.raises(NotImplementedError):
        await memory_saver.get("some-thread")


@pytest.mark.asyncio
async def test_get_all_not_implemented_raises(memory_saver: MemorySaver):
    """The base MemorySaver.get_all should raise NotImplementedError indicating subclasses must implement it."""
    with pytest.raises(NotImplementedError):
        await memory_saver.get_all("some-thread")