"""Unit tests for the memory persistence helpers."""

from __future__ import annotations

from typing import List

import pytest

from app.bot.memory import MemorySaverInMemory
from app.bot.memory.models import State


@pytest.fixture(name="memory_saver")
def fixture_memory_saver() -> MemorySaverInMemory:
    """Provide a fresh in-memory saver for each test."""
    return MemorySaverInMemory()


@pytest.mark.asyncio
async def test_memorysaver_init_state_returns_new_state_with_thread_id() -> None:
    """init_state should produce a fresh State instance scoped to the provided thread."""
    saver = MemorySaverInMemory()

    first_state = await saver.init_state("thread-alpha")
    second_state = await saver.init_state("thread-alpha")

    assert isinstance(first_state, State)
    assert first_state.thread_id == "thread-alpha"
    assert first_state is not second_state


@pytest.mark.asyncio
async def test_memorysaver_inmemory_save_and_get_returns_latest_state(
    memory_saver: MemorySaverInMemory,
) -> None:
    """get should always return the most recently saved state for the thread."""
    state_one = State(thread_id="thread-one")
    state_two = State(thread_id="thread-one")

    await memory_saver.save("thread-one", state_one)
    await memory_saver.save("thread-one", state_two)

    latest_state = await memory_saver.get("thread-one")

    assert latest_state is state_two


@pytest.mark.asyncio
async def test_memorysaver_inmemory_get_returns_none_for_unknown_thread(
    memory_saver: MemorySaverInMemory,
) -> None:
    """get should return None when no history exists for the requested thread."""
    result = await memory_saver.get("missing-thread")

    assert result is None


@pytest.mark.asyncio
async def test_memorysaver_inmemory_get_all_returns_entire_history_in_order(
    memory_saver: MemorySaverInMemory,
) -> None:
    """get_all should return the saved states in chronological order."""
    states: List[State] = [
        State(thread_id="thread-two", current_node="first"),
        State(thread_id="thread-two", current_node="second"),
    ]

    for state in states:
        await memory_saver.save("thread-two", state)

    history = await memory_saver.get_all("thread-two")

    assert history == states
    assert history is not states


@pytest.mark.asyncio
async def test_memorysaver_inmemory_get_all_returns_copy_of_history(
    memory_saver: MemorySaverInMemory,
) -> None:
    """Mutating the list returned by get_all must not alter the stored history."""
    saved_states = [State(thread_id="thread-three"), State(thread_id="thread-three")]
    for state in saved_states:
        await memory_saver.save("thread-three", state)

    first_history = await memory_saver.get_all("thread-three")
    first_history.append(State(thread_id="thread-three"))

    second_history = await memory_saver.get_all("thread-three")

    assert len(second_history) == len(saved_states)
    assert second_history == saved_states


@pytest.mark.asyncio
async def test_memorysaver_inmemory_get_all_returns_empty_list_for_missing_thread(
    memory_saver: MemorySaverInMemory,
) -> None:
    """get_all should gracefully return an empty list when no thread history exists."""
    history = await memory_saver.get_all("ghost-thread")

    assert history == []
    assert history is not None
    assert isinstance(history, list)