from app.bot.memory.models import State


class Msg:
    def __init__(self, text, context=None):
        self.text = text
        self.context = context or {}

    def to_dict(self):
        return {"text": self.text, "context": self.context}


def test_state_defaults_and_to_dict():
    st = State(thread_id="t1")
    d = st.to_dict()
    assert d["thread_id"] == "t1"
    assert d["user_message"] is None
    assert "date" in d and d["date"] is not None
    assert st.VERSION == "1.0"


def test_state_update_merges_context_and_resets_when_complete():
    st = State(
        thread_id="t1",
        context={"a": 1},
        complete=True,
        intent={"id": "x"},
        parameters=[{"name": "p"}],
        extracted_parameters={"k": "v"},
        missing_parameters=["m"],
        current_node="node",
        bot_message=[{"text": "hi"}],
    )
    msg = Msg("hello", {"b": 2})
    st.update(msg)
    assert st.user_message.text == "hello"
    assert st.context == {"a": 1, "b": 2}
    assert st.complete is False
    assert st.parameters == []
    assert st.extracted_parameters == {}
    assert st.missing_parameters == []
    assert st.current_node is None
    assert st.bot_message == []


def test_get_active_intent_id():
    st = State(thread_id="t")
    assert st.get_active_intent_id() is None
    st.intent = {"id": "intent-1"}
    assert st.get_active_intent_id() == "intent-1"