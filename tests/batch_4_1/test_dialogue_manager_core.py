import asyncio
import pytest

from app.bot.memory import MemorySaverInMemory
from app.bot.memory.models import State
from app.bot.dialogue_manager.models import (
    IntentModel,
    ParameterModel,
    ApiDetailsModel,
    UserMessage,
)
from app.bot.dialogue_manager.dialogue_manager import DialogueManager, DialogueManagerException
from app.bot.dialogue_manager import dialogue_manager as dm_mod


class DummyPipeline:
    def __init__(self, entities=None, intent_id="greet", confidence=1.0):
        self.entities = entities or {}
        self.intent_id = intent_id
        self.confidence = confidence

    def process(self, data):
        return {
            "entities": self.entities,
            "intent": {"intent": self.intent_id, "confidence": self.confidence},
        }


def make_dm(intents=None, threshold=0.6):
    intents = intents or [
        IntentModel(name="Greet", intent_id="greet", speech_response="Hi"),
        IntentModel(name="Fallback", intent_id="fallback", speech_response="Sorry"),
    ]
    mem = MemorySaverInMemory()
    pipe = DummyPipeline()
    return DialogueManager(
        memory_saver=mem,
        intents=intents,
        nlu_pipeline=pipe,
        fallback_intent_id="fallback",
        intent_confidence_threshold=threshold,
    )


def test_get_intent_id_and_confidence_slash_command():
    dm = make_dm()
    st = State(thread_id="t1", user_message=UserMessage("t1", "/order", {}))
    intent_id, conf = dm._get_intent_id_and_confidence(st, {"intent": {"intent": "greet", "confidence": 0.9}})
    assert intent_id == "order"
    assert conf == 1.0


def test_get_intent_id_and_confidence_threshold_fallback():
    dm = make_dm(threshold=0.8)
    st = State(thread_id="t1", user_message=UserMessage("t1", "hello", {}))
    nlu = {"intent": {"intent": "greet", "confidence": 0.5}}
    intent_id, conf = dm._get_intent_id_and_confidence(st, nlu)
    assert intent_id == "fallback"
    assert conf == 1.0


def test_get_intent_id_and_confidence_normal():
    dm = make_dm(threshold=0.5)
    st = State(thread_id="t1", user_message=UserMessage("t1", "hello", {}))
    nlu = {"intent": {"intent": "greet", "confidence": 0.9}}
    intent_id, conf = dm._get_intent_id_and_confidence(st, nlu)
    assert intent_id == "greet"
    assert conf == 0.9


def test_process_intent_entity_matching_and_completion():
    # Active intent requires a city parameter of type 'location'
    ai = IntentModel(
        name="Order",
        intent_id="order",
        speech_response="",
        parameters=[ParameterModel(name="city", required=True, type="location")],
    )
    dm = make_dm(intents=[ai, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])
    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}))
    st.nlu = {"entities": {"location": "NYC"}}

    st2, active_intent = dm._process_intent(ai, ai, st)
    assert active_intent.intent_id == "order"
    assert st2.extracted_parameters["city"] == "NYC"
    assert st2.missing_parameters == []
    assert st2.complete is True


def test_process_intent_free_text_prompt_fills_and_completes():
    ai = IntentModel(
        name="Feedback",
        intent_id="feedback",
        speech_response="",
        parameters=[ParameterModel(name="notes", required=True, type="free_text")],
    )
    dm = make_dm(intents=[ai, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])
    st = State(thread_id="t1", user_message=UserMessage("t1", "Great service!", {}))
    st.current_node = "notes"  # simulates being prompted for free_text
    st.nlu = {"entities": {}}

    st2, _ = dm._process_intent(ai, ai, st)
    assert st2.extracted_parameters["notes"] == "Great service!"
    assert st2.complete is True


def test_process_intent_missing_parameters_sets_prompt():
    ai = IntentModel(
        name="Order",
        intent_id="order",
        speech_response="",
        parameters=[
            ParameterModel(name="city", required=True, type="location", prompt="Enter city###Now zip"),
            ParameterModel(name="zip", required=True, type="zip"),
        ],
    )
    dm = make_dm(intents=[ai, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])
    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}))
    st.nlu = {"entities": {}}  # nothing extracted

    st2, _ = dm._process_intent(ai, ai, st)
    assert st2.current_node == "city"
    assert [m["text"] for m in st2.bot_message] == ["Enter city", "Now zip"]
    assert st2.complete is False


def test_cancel_intent_resets_state():
    cancel_intent = IntentModel(name="Cancel", intent_id="cancel", speech_response="")
    active_intent = IntentModel(name="Order", intent_id="order", speech_response="")
    dm = make_dm(intents=[cancel_intent, active_intent, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])

    st = State(
        thread_id="t1",
        user_message=UserMessage("t1", "cancel", {}),
        intent={"id": "order"},
        parameters=[{"name": "x", "type": "t", "required": True}],
        extracted_parameters={"x": 1},
        missing_parameters=["y"],
        complete=False,
        current_node="x",
    )

    st2, act = dm._process_intent(cancel_intent, active_intent, st)
    assert act.intent_id == "cancel"
    assert st2.complete is True
    assert st2.parameters == []
    assert st2.extracted_parameters == {}
    assert st2.missing_parameters == []
    assert st2.current_node is None


@pytest.mark.asyncio
async def test_handle_api_trigger_non_api_renders_template():
    intent = IntentModel(
        name="Greet",
        intent_id="greet",
        speech_response="Hello {{parameters.name}} from {{context.country}}",
        api_trigger=False,
    )
    dm = make_dm(intents=[intent, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])

    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}), context={"country": "US"})
    st.extracted_parameters = {"name": "Sam"}

    st2 = await dm._handle_api_trigger(intent, st)
    assert [m["text"] for m in st2.bot_message] == ["Hello Sam from US"]


@pytest.mark.asyncio
async def test_handle_api_trigger_with_success(monkeypatch):
    intent = IntentModel(
        name="Check",
        intent_id="check",
        speech_response="Price is {{ result.price }}",
        api_trigger=True,
        api_details=ApiDetailsModel(url="https://api/x", request_type="GET", headers=[]),
    )
    dm = make_dm(intents=[intent, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])

    async def fake_call_api(url, method, headers, parameters, is_json):
        return {"price": 42}

    monkeypatch.setattr(dm_mod, "call_api", fake_call_api)

    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}))
    st.extracted_parameters = {}

    st2 = await dm._handle_api_trigger(intent, st)
    assert [m["text"] for m in st2.bot_message] == ["Price is 42"]


@pytest.mark.asyncio
async def test_handle_api_trigger_with_failure(monkeypatch):
    intent = IntentModel(
        name="Check",
        intent_id="check",
        speech_response="Will not be used",
        api_trigger=True,
        api_details=ApiDetailsModel(url="https://api/x", request_type="GET", headers=[]),
    )
    dm = make_dm(intents=[intent, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])

    class Boom(Exception):
        pass

    async def bad_call_api(url, method, headers, parameters, is_json):
        # Simulate APICallExcetion flow in _call_intent_api by raising DialogueManagerException from wrapper
        raise dm_mod.APICallExcetion("fail")

    # Patch lower-level call_api and let _call_intent_api convert it
    monkeypatch.setattr(dm_mod, "call_api", bad_call_api)

    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}))
    st.extracted_parameters = {}

    st2 = await dm._handle_api_trigger(intent, st)
    # Fallback message text
    assert [m["text"] for m in st2.bot_message] == ["Service is not available. Please try again later."]


@pytest.mark.asyncio
async def test_call_intent_api_builds_url_and_payload_json(monkeypatch):
    intent = IntentModel(
        name="Submit",
        intent_id="submit",
        speech_response="",
        api_trigger=True,
        api_details=ApiDetailsModel(
            url="https://api/items/{{ parameters.id }}?u={{ context.user }}",
            request_type="POST",
            headers=[{"headerKey": "X", "headerValue": "1"}],
            is_json=True,
            json_data='{"id": "{{ parameters.id }}", "user": "{{ context.user }}"}',
        ),
    )

    dm = make_dm(intents=[intent, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])

    called = {}

    async def spy_call_api(url, method, headers, parameters, is_json):
        called.update(dict(url=url, method=method, headers=headers, parameters=parameters, is_json=is_json))
        return {"ok": True}

    monkeypatch.setattr(dm_mod, "call_api", spy_call_api)

    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}), context={"user": "bob"})
    st.extracted_parameters = {"id": "42"}

    result = await dm._call_intent_api(intent, st)
    assert result == {"ok": True}
    assert called["url"] == "https://api/items/42?u=bob"
    assert called["method"] == "POST"
    assert called["headers"] == {"X": "1"}
    assert called["parameters"] == {"id": "42", "user": "bob"}
    assert called["is_json"] is True


@pytest.mark.asyncio
async def test_call_intent_api_builds_url_and_params_non_json(monkeypatch):
    intent = IntentModel(
        name="Fetch",
        intent_id="fetch",
        speech_response="",
        api_trigger=True,
        api_details=ApiDetailsModel(
            url="https://api/search",
            request_type="GET",
            headers=[],
            is_json=False,
        ),
    )

    dm = make_dm(intents=[intent, IntentModel(name="Fallback", intent_id="fallback", speech_response="")])

    called = {}

    async def spy_call_api(url, method, headers, parameters, is_json):
        called.update(dict(url=url, method=method, headers=headers, parameters=parameters, is_json=is_json))
        return {"ok": True}

    monkeypatch.setattr(dm_mod, "call_api", spy_call_api)

    st = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}), context={})
    st.extracted_parameters = {"q": "pizza"}

    result = await dm._call_intent_api(intent, st)
    assert result == {"ok": True}
    assert called["url"] == "https://api/search"
    assert called["method"] == "GET"
    assert called["parameters"] == {"q": "pizza"}
    assert called["is_json"] is False


def test_process_raises_when_pipeline_not_initialized():
    # Build dm with nlu_pipeline None
    mem = MemorySaverInMemory()
    intents = [IntentModel(name="Fallback", intent_id="fallback", speech_response="")]
    dm = DialogueManager(
        memory_saver=mem,
        intents=intents,
        nlu_pipeline=None,
        fallback_intent_id="fallback",
        intent_confidence_threshold=0.5,
    )
    msg = UserMessage("t1", "hello", {})

    with pytest.raises(DialogueManagerException):
        asyncio.get_event_loop().run_until_complete(dm.process(msg))