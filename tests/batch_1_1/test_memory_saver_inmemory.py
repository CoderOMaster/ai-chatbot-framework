import pytest

from app.bot.memory import MemorySaverInMemory
from app.bot.memory.models import State


@pytest.mark.asyncio
async def test_inmemory_saver_save_and_get_and_get_all():
    saver = MemorySaverInMemory()

    assert await saver.get("t1") is None
    assert await saver.get_all("t1") == []

    s1 = State(thread_id="t1")
    s2 = State(thread_id="t1", context={"a": 1})

    await saver.save("t1", s1)
    await saver.save("t1", s2)

    last = await saver.get("t1")
    assert last is s2

    all_states = await saver.get_all("t1")
    assert all_states == [s1, s2]