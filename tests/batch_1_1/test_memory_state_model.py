import pytest
from datetime import datetime
from app.bot.memory.models import State
from app.bot.dialogue_manager.models import UserMessage


@pytest.mark.asyncio
async def test_state_to_from_dict_roundtrip_preserves_core_fields():
    um = UserMessage(thread_id="t1", text="hi", context={"a": 1})
    s = State(
        thread_id="t1",
        user_message=um,
        bot_message=[{"text": "hello"}],
        context={"a": 1},
        intent={"id": "i1"},
        parameters=[{"name": "p1", "required": True}],
        extracted_parameters={"p1": "v1"},
        missing_parameters=["p2"],
        complete=False,
        current_node="node1",
        version="1.0",
    )

    d = s.to_dict()
    # date should be datetime
    assert isinstance(d["date"], datetime)

    s2 = State.from_dict(d)
    assert s2.thread_id == "t1"
    assert s2.context == {"a": 1}
    assert s2.intent == {"id": "i1"}
    assert s2.parameters == [{"name": "p1", "required": True}]
    assert s2.extracted_parameters == {"p1": "v1"}
    assert s2.missing_parameters == ["p2"]
    assert s2.complete is False
    assert s2.current_node == "node1"
    assert s2.version == "1.0"


@pytest.mark.asyncio
async def test_state_update_sets_user_message_and_refreshes_date_and_context_merging():
    s = State(thread_id="t1", context={"a": 1})
    before_date = s.date
    um = UserMessage(thread_id="t1", text="hello", context={"b": 2})

    s.update(um)

    assert s.user_message is um
    assert s.date >= before_date
    assert s.context == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_state_update_resets_when_complete():
    s = State(
        thread_id="t1",
        intent={"id": "i1"},
        parameters=[{"x": 1}],
        extracted_parameters={"y": 2},
        missing_parameters=["z"],
        complete=True,
        current_node="old",
    )

    um = UserMessage(thread_id="t1", text="hello", context={})
    s.update(um)

    assert s.bot_message == []
    assert s.intent is None
    assert s.parameters == []
    assert s.extracted_parameters == {}
    assert s.missing_parameters == []
    assert s.complete is False
    assert s.current_node is None


@pytest.mark.asyncio
async def test_get_active_intent_id():
    s = State(thread_id="t1")
    assert s.get_active_intent_id() is None

    s.intent = {"id": "abc"}
    assert s.get_active_intent_id() == "abc"