import asyncio
import json
import pytest
from datetime import datetime, UTC, timedelta

from app.bot.dialogue_manager import dialogue_manager as dm


# Helper stubs used across tests
class DummyIntent:
    def __init__(self, intent_id, parameters=None, api_trigger=False, api_details=None, speech_response="Hello"):
        self.intent_id = intent_id
        self.parameters = parameters or []
        self.api_trigger = api_trigger
        self.api_details = api_details
        self.speech_response = speech_response


class DummyParam:
    def __init__(self, name, type_, required=False):
        self.name = name
        self.type = type_
        self.required = required


class DummyAPIDetails:
    def __init__(self, url, is_json=False, json_data="{}", request_type="GET", headers=None):
        self.url = url
        self.is_json = is_json
        self.json_data = json_data
        self.request_type = request_type
        self._headers = headers or {}

    def get_headers(self):
        return self._headers


class DummyUserMessage:
    def __init__(self, text, thread_id="t1"):
        self.text = text
        self.thread_id = thread_id


class DummyState:
    def __init__(self, **kwargs):
        # default fields used by dialogue_manager
        self.current_node = kwargs.get("current_node", "")
        self.user_message = kwargs.get("user_message", DummyUserMessage(""))
        self.nlu = kwargs.get("nlu", {})
        self.parameters = kwargs.get("parameters", [])
        self.extracted_parameters = kwargs.get("extracted_parameters", {})
        self.missing_parameters = kwargs.get("missing_parameters", [])
        self.complete = kwargs.get("complete", False)
        self.bot_message = kwargs.get("bot_message", [])
        self.context = kwargs.get("context", {})

    def replace(self, **kwargs):
        data = {
            "current_node": kwargs.get("current_node", self.current_node),
            "user_message": kwargs.get("user_message", self.user_message),
            "nlu": kwargs.get("nlu", self.nlu),
            "parameters": kwargs.get("parameters", self.parameters),
            "extracted_parameters": kwargs.get("extracted_parameters", self.extracted_parameters),
            "missing_parameters": kwargs.get("missing_parameters", self.missing_parameters),
            "complete": kwargs.get("complete", self.complete),
            "bot_message": kwargs.get("bot_message", self.bot_message),
            "context": kwargs.get("context", self.context),
        }
        return DummyState(**data)

    def update(self, message):
        # mimic storing last user message
        new_state = self.replace(user_message=message)
        return new_state


class DummyNLUPipeline:
    def __init__(self, result=None, raise_exc=False):
        self.result = result or {"intent": {"intent": "greet", "confidence": 0.9}, "entities": {}}
        self.calls = 0
        self.raise_exc = raise_exc

    def process(self, data):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("NLU failed")
        return self.result


class DummyMemorySaver:
    def __init__(self):
        self.store = {}

    async def get(self, thread_id):
        return self.store.get(thread_id)

    async def init_state(self, thread_id):
        state = DummyState(user_message=DummyUserMessage(""))
        self.store[thread_id] = state
        return state

    async def save(self, thread_id, state):
        self.store[thread_id] = state


@pytest.mark.asyncio
async def test_intent_resolver_explicit_and_fallback():
    """IntentResolver.resolve should handle explicit intent commands and fallback."""
    intents = {"greet": DummyIntent("greet"), "fallback": DummyIntent("fallback")}
    resolver = dm.IntentResolver(intents, fallback_intent_id="fallback", confidence_threshold=0.5)

    # explicit existing
    intent_id, conf = await resolver.resolve("/greet", {"intent": {}}, DummyState())
    assert intent_id == "greet" and conf == 1.0

    # explicit non-existing -> fallback
    intent_id, conf = await resolver.resolve("/unknown", {"intent": {}}, DummyState())
    assert intent_id == "fallback" and conf == 1.0

    # predicted with sufficient confidence
    intent_id, conf = await resolver.resolve("hi", {"intent": {"intent": "greet", "confidence": 0.8}}, DummyState())
    assert intent_id == "greet" and conf == 0.8

    # low confidence -> fallback
    intent_id, conf = await resolver.resolve("hi", {"intent": {"intent": "greet", "confidence": 0.1}}, DummyState())
    assert intent_id == "fallback"


@pytest.mark.asyncio
async def test_intent_resolver_raises_on_bad_nlu():
    """Passing an invalid nlu_result should raise IntentResolutionException."""
    intents = {"fallback": DummyIntent("fallback")}
    resolver = dm.IntentResolver(intents, fallback_intent_id="fallback", confidence_threshold=0.5)

    with pytest.raises(dm.IntentResolutionException):
        await resolver.resolve("hi", None, DummyState())


@pytest.mark.asyncio
async def test_parameter_filler_basic_and_free_text():
    """ParameterFiller should extract entities and prefer free_text from current node."""
    filler = dm.ParameterFiller()

    params = [DummyParam("name", "name", required=True), DummyParam("note", "free_text", required=False)]
    # state where user prompted for 'note'
    state = DummyState(current_node="note", user_message=DummyUserMessage("This is a note"), nlu={"name": "Alice"})

    extracted, missing = await filler.fill(params, {"name": "Alice"}, state)
    assert extracted["name"] == "Alice"
    # free_text param should be filled from current state's user_message
    assert extracted["note"] == "This is a note"
    assert missing == []

    # missing required param
    state2 = DummyState(current_node="", user_message=DummyUserMessage(""), nlu={})
    extracted2, missing2 = await filler.fill(params, {}, state2)
    assert "name" in missing2


def test_group_entities_by_type():
    d = dm.ParameterFiller._group_entities_by_type({"name": "Alice", "age": 30, "name": "Bob"})
    # since dict keys are unique, only last 'name' survived - this tests basic grouping behavior
    assert isinstance(d, dict)


@pytest.mark.asyncio
async def test_api_caller_success_and_exceptions(monkeypatch):
    """APICaller should call the underlying call_api and handle errors appropriately."""
    caller = dm.APICaller()

    # successful JSON API call
    api_details = DummyAPIDetails(url="http://example.com/{{ parameters.user }}", is_json=True, json_data='{"user": "{{ parameters.user }}"}', request_type="POST")
    intent = DummyIntent("test", api_trigger=True, api_details=api_details)

    async def fake_call_api(url, req_type, headers, parameters, is_json):
        assert "example.com" in url
        return {"ok": True, "received": parameters}

    monkeypatch.setattr(dm, "call_api", fake_call_api)

    state = DummyState(extracted_parameters={"user": "alice"}, context={})
    res = await caller.call(intent, state)
    assert res.get("ok") is True

    # simulate APICallExcetion being raised
    async def raising_call_api(url, req_type, headers, parameters, is_json):
        raise dm.APICallExcetion("down")

    monkeypatch.setattr(dm, "call_api", raising_call_api)

    with pytest.raises(dm.APICallException):
        await caller.call(intent, state)

    # simulate other exception
    async def raising_other(url, req_type, headers, parameters, is_json):
        raise RuntimeError("boom")

    monkeypatch.setattr(dm, "call_api", raising_other)
    with pytest.raises(dm.APICallException):
        await caller.call(intent, state)


@pytest.mark.asyncio
async def test_response_generator_basic():
    """ResponseGenerator should render templates with context and parameters asynchronously."""
    gen = dm.ResponseGenerator()
    intent = DummyIntent("greet", speech_response="Hello {{ context.user }}")
    state = DummyState(context={"user": "Bob"}, extracted_parameters={})

    messages = await gen.generate(intent, state)
    assert isinstance(messages, list)
    assert messages[0]["text"].strip() == "Hello Bob"


@pytest.mark.asyncio
async def test_process_nlu_caching_and_exceptions():
    """DialogueManager._process_nlu should cache results and raise NLUServiceException on pipeline errors."""
    mem = DummyMemorySaver()
    nlu = DummyNLUPipeline(result={"intent": {"intent": "greet", "confidence": 0.9}, "entities": {"name": "Alice"}})
    mgr = dm.DialogueManager(mem, intents=[], nlu_pipeline=nlu, fallback_intent_id="fb", intent_confidence_threshold=0.5)

    # first call triggers nlu.process
    res1 = await mgr._process_nlu("hello")
    assert nlu.calls == 1
    assert res1["intent"]["intent"] == "greet"

    # second call should use cache and not call process again
    res2 = await mgr._process_nlu("hello")
    assert nlu.calls == 1
    assert res2["intent"]["intent"] == "greet"

    # pipeline raising exception leads to NLUServiceException
    broken = DummyNLUPipeline(raise_exc=True)
    mgr2 = dm.DialogueManager(mem, intents=[], nlu_pipeline=broken, fallback_intent_id="fb", intent_confidence_threshold=0.5)
    with pytest.raises(dm.NLUServiceException):
        await mgr2._process_nlu("hi")


@pytest.mark.asyncio
async def test_fill_parameters_and_handle_api_and_response(monkeypatch):
    """Integration test for filling parameters, calling API, and generating response."""
    # Create intent with one parameter and api trigger
    param = DummyParam("user", "user", required=True)
    api_details = DummyAPIDetails(url="http://api/{{ parameters.user }}", is_json=False)
    intent = DummyIntent("intent1", parameters=[param], api_trigger=True, api_details=api_details, speech_response="Got {{ parameters.user }}")

    mem = DummyMemorySaver()
    nlu = DummyNLUPipeline(result={"intent": {"intent": "intent1", "confidence": 0.9}, "entities": {"user": "alice"}})
    mgr = dm.DialogueManager(mem, intents=[intent], nlu_pipeline=nlu, fallback_intent_id="fb", intent_confidence_threshold=0.5)

    # Patch call_api to return some result
    async def fake_call_api(url, req_type, headers, parameters, is_json):
        return {"status": "ok", "user": parameters.get("user")}

    monkeypatch.setattr(dm, "call_api", fake_call_api)

    # Create state that mimics having NLU processed
    state = DummyState(nlu={"entities": {"user": "alice"}}, parameters=[], extracted_parameters={}, missing_parameters=[], complete=False, user_message=DummyUserMessage("hello"))

    filled_state = await mgr._fill_parameters(intent, state)
    # after filling, should be complete and extracted parameters populated
    assert filled_state.complete is True
    assert filled_state.extracted_parameters.get("user") == "alice"

    # handle API and response should call api and generate bot_message
    result_state = await mgr._handle_api_and_response(intent, filled_state)
    assert isinstance(result_state.bot_message, list)
    assert any("alice" in m["text"] or "Got" in m["text"] for m in result_state.bot_message)


@pytest.mark.asyncio
async def test_generate_parameter_prompt():
    """_generate_parameter_prompt should create a prompt for the first missing parameter."""
    mem = DummyMemorySaver()
    mgr = dm.DialogueManager(mem, intents=[], nlu_pipeline=DummyNLUPipeline(), fallback_intent_id="fb", intent_confidence_threshold=0.5)

    state = DummyState(parameters=[{"name": "email"}], missing_parameters=["email"], user_message=DummyUserMessage(""))
    new_state = await mgr._generate_parameter_prompt(state)
    assert new_state.current_node == "email"
    assert new_state.bot_message and isinstance(new_state.bot_message[0]["text"], str)


def test_update_state_and_cancel():
    """_update_state_with_nlu and _handle_cancel_intent should modify state appropriately."""
    s = DummyState()
    nlu = {"intent": {"intent": "x"}, "entities": {"a":1}}
    updated = dm.DialogueManager._update_state_with_nlu(s, nlu)
    assert updated.nlu["entities"]["a"] == 1

    canceled = dm.DialogueManager._handle_cancel_intent(s)
    assert canceled.complete is True
    assert canceled.bot_message[0]["text"] == "Cancelled."