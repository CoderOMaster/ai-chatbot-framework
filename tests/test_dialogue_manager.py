import pytest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from app.bot.dialogue_manager.dialogue_manager import (
    AsyncAPICaller,
    DialogueManager,
    DialogueManagerConfig,
    DialogueManagerException,
)
from app.bot.dialogue_manager.http_client import HTTPResponse, APICallExcetion
from app.bot.dialogue_manager.models import (
    ApiDetailsModel,
    IntentModel,
    ParameterModel,
    UserMessage,
)
from app.bot.memory import MemorySaverInMemory
from app.bot.memory.models import State


@dataclass
class DummyIntent:
    name: str
    intentId: str
    speechResponse: str
    userDefined: bool
    apiTrigger: bool = False
    apiDetails: Optional[Any] = None
    parameters: Optional[List[Any]] = None


@dataclass
class DummyTraditionalSettings:
    intent_detection_threshold: float


@dataclass
class DummyNLUConfig:
    traditional_settings: DummyTraditionalSettings


@dataclass
class DummyBot:
    nlu_config: DummyNLUConfig


class FakeIntentRepository:
    def __init__(self, intents: List[DummyIntent]) -> None:
        self._intents = intents
        self.list_intents_called = False

    async def list_intents(self) -> List[DummyIntent]:
        self.list_intents_called = True
        return self._intents


class FakeBotRepository:
    def __init__(self, threshold: float) -> None:
        self._bot = DummyBot(
            nlu_config=DummyNLUConfig(
                traditional_settings=DummyTraditionalSettings(threshold)
            )
        )
        self.get_bot_called = False

    async def get_bot(self, _bot_name: str) -> DummyBot:
        self.get_bot_called = True
        return self._bot


class DummyNLUPipeline:
    def __init__(
        self,
        process_result: Optional[Dict[str, Any]] = None,
        load_result: bool = True,
    ) -> None:
        self.process_result = process_result or {
            "intent": {"intent": "sample", "confidence": 1.0},
            "entities": {},
        }
        self.load_result = load_result
        self.load_calls: List[str] = []

    def load(self, models_dir: str) -> bool:
        self.load_calls.append(models_dir)
        return self.load_result

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return self.process_result


class FakeAPICaller:
    def __init__(self, response: HTTPResponse, should_raise: bool = False) -> None:
        self.response = response
        self.should_raise = should_raise
        self.called_args: Optional[tuple] = None

    async def __call__(
        self,
        url: str,
        method: str,
        headers: Optional[Dict[str, str]],
        parameters: Optional[Dict[str, Any]],
        is_json: bool,
    ) -> HTTPResponse:
        self.called_args = (url, method, headers, parameters, is_json)
        if self.should_raise:
            raise APICallExcetion("failed request")
        return self.response


async def _noop_api_caller(*args: Any, **kwargs: Any) -> HTTPResponse:
    return HTTPResponse(status=200, body={}, headers={})


def _build_dialogue_manager(
    *,
    intents: Optional[List[IntentModel]] = None,
    fallback_intent_id: str = "fallback",
    confidence_threshold: float = 0.5,
    pipeline: Optional[DummyNLUPipeline] = None,
    api_caller: AsyncAPICaller = _noop_api_caller,
) -> DialogueManager:
    base_intents = intents or [
        IntentModel(name="Fallback", intent_id=fallback_intent_id, speech_response="fallback")
    ]

    if fallback_intent_id not in [intent.intent_id for intent in base_intents]:
        base_intents.append(
            IntentModel(name="Fallback", intent_id=fallback_intent_id, speech_response="fallback")
        )

    return DialogueManager(
        memory_saver=MemorySaverInMemory(),
        intents=base_intents,
        nlu_pipeline=pipeline or DummyNLUPipeline(),
        fallback_intent_id=fallback_intent_id,
        intent_confidence_threshold=confidence_threshold,
        api_caller=api_caller,
    )


def _create_user_message(thread: str, text: str) -> UserMessage:
    return UserMessage(thread_id=thread, text=text, context={})


@pytest.mark.asyncio
async def test_from_config_applies_explicit_threshold() -> None:
    """Ensure the manager respects an explicitly provided confidence threshold."""
    intents = [
        DummyIntent(
            name="fallback",
            intentId="fallback",
            speechResponse="Fallback response",
            userDefined=True,
        )
    ]
    intent_repository = FakeIntentRepository(intents)
    bot_repository = FakeBotRepository(threshold=0.3)
    config = DialogueManagerConfig(
        fallback_intent_id="fallback",
        bot_name="bot-alpha",
        intent_confidence_threshold=0.75,
    )

    manager = await DialogueManager.from_config(
        intent_repository=intent_repository,
        bot_repository=bot_repository,
        memory_saver=MemorySaverInMemory(),
        nlu_pipeline=DummyNLUPipeline(),
        config=config,
    )

    assert manager.confidence_threshold == 0.75
    assert intent_repository.list_intents_called
    assert bot_repository.get_bot_called
    assert "fallback" in manager.intents


@pytest.mark.asyncio
async def test_from_config_uses_bot_threshold_when_missing() -> None:
    """Verify the threshold falls back to the bot store when not provided."""
    intents = [
        DummyIntent(
            name="fallback",
            intentId="fallback",
            speechResponse="Fallback response",
            userDefined=True,
        )
    ]
    intent_repository = FakeIntentRepository(intents)
    bot_repository = FakeBotRepository(threshold=0.4)
    config = DialogueManagerConfig(
        fallback_intent_id="fallback",
        bot_name="bot-beta",
        intent_confidence_threshold=None,
    )

    manager = await DialogueManager.from_config(
        intent_repository=intent_repository,
        bot_repository=bot_repository,
        memory_saver=MemorySaverInMemory(),
        nlu_pipeline=DummyNLUPipeline(),
        config=config,
    )

    assert manager.confidence_threshold == 0.4


def test_update_model_handles_reload_failure() -> None:
    """Reload failures should clear the cached pipeline reference."""
    pipeline = DummyNLUPipeline(load_result=False)
    manager = _build_dialogue_manager(pipeline=pipeline)

    manager.update_model("/models/path")

    assert manager.nlu_pipeline is None
    assert pipeline.load_calls == ["/models/path"]


@pytest.mark.asyncio
async def test_process_raises_when_pipeline_uninitialized() -> None:
    """Processing should fail fast when no pipeline has been loaded."""
    manager = DialogueManager(
        memory_saver=MemorySaverInMemory(),
        intents=[
            IntentModel(name="fallback", intent_id="fallback", speech_response="none")
        ],
        nlu_pipeline=None,
        fallback_intent_id="fallback",
        intent_confidence_threshold=0.5,
        api_caller=_noop_api_caller,
    )

    with pytest.raises(DialogueManagerException):
        await manager.process(_create_user_message("thread-1", "hello"))


def test_get_intent_id_and_confidence_handles_command_input() -> None:
    """Shortcut commands should bypass intent recognition confidence checks."""
    manager = _build_dialogue_manager()
    state = State(thread_id="thread-1")
    state.user_message = _create_user_message("thread-1", "/help")

    intent_id, confidence = manager._get_intent_id_and_confidence(state, {})

    assert intent_id == "help"
    assert confidence == 1.0


def test_get_intent_id_and_confidence_below_threshold_returns_fallback() -> None:
    """Low confidence predictions should fall back to the safe intent."""
    manager = _build_dialogue_manager(confidence_threshold=0.6)
    state = State(thread_id="thread-2")
    state.user_message = _create_user_message("thread-2", "hi")
    result = {"intent": {"intent": "ask", "confidence": 0.3}}

    intent_id, confidence = manager._get_intent_id_and_confidence(state, result)

    assert intent_id == manager.fallback_intent_id
    assert confidence == 1.0


def test_get_intent_id_and_confidence_above_threshold_returns_prediction() -> None:
    """Valid predictions should be accepted when confidence is sufficient."""
    manager = _build_dialogue_manager(confidence_threshold=0.5)
    state = State(thread_id="thread-2")
    state.user_message = _create_user_message("thread-2", "hi")
    result = {"intent": {"intent": "ask", "confidence": 0.9}}

    intent_id, confidence = manager._get_intent_id_and_confidence(state, result)

    assert intent_id == "ask"
    assert confidence == 0.9


def test_get_fallback_intent_returns_configured_model() -> None:
    """The configured fallback intent should be retrievable through the helper."""
    manager = _build_dialogue_manager()

    fallback_intent = manager._get_fallback_intent()

    assert fallback_intent.intent_id == "fallback"


def test_process_intent_handles_cancel_intent() -> None:
    """Cancel intent execution should clear the tracked state and mark completion."""
    cancel_intent = IntentModel(
        name="Cancel",
        intent_id="cancel",
        speech_response="Canceled",
    )
    active_intent = IntentModel(
        name="Active",
        intent_id="active",
        speech_response="OK",
    )
    state = State(thread_id="thread-3")
    state.parameters = [{"name": "foo"}]
    state.extracted_parameters = {"foo": "value"}
    state.missing_parameters = ["foo"]
    state.current_node = "foo"

    manager = _build_dialogue_manager(intents=[cancel_intent, active_intent])
    updated, active = manager._process_intent(cancel_intent, active_intent, state)

    assert updated.complete
    assert updated.parameters == []
    assert updated.extracted_parameters == {}
    assert updated.missing_parameters == []
    assert updated.current_node is None
    assert active.intent_id == "cancel"


def test_process_intent_tracks_missing_required_parameters() -> None:
    """Required parameters that are not yet provided should trigger a prompt."""
    parameter = ParameterModel(
        name="email",
        required=True,
        type="email",
        prompt="Your email please###Thanks",
    )
    query_intent = IntentModel(
        name="CollectEmail",
        intent_id="collect_email",
        speech_response="Got it",
        parameters=[parameter],
    )
    state = State(thread_id="thread-4")
    state.nlu = {"entities": {}}

    manager = _build_dialogue_manager(intents=[query_intent])
    updated, _ = manager._process_intent(query_intent, query_intent, state)

    assert updated.missing_parameters == ["email"]
    assert updated.current_node == "email"
    assert updated.bot_message == [
        {"text": "Your email please"},
        {"text": "Thanks"},
    ]
    assert not updated.complete


@pytest.mark.asyncio
async def test_handle_api_trigger_without_api_renders_response() -> None:
    """Simple speech responses should be rendered even when no API is required."""
    intent = IntentModel(
        name="Hello",
        intent_id="hello",
        speech_response="Hello there###Again",
        api_trigger=False,
    )
    state = State(thread_id="thread-5")
    state.context = {"user": "tester"}
    state.extracted_parameters = {"foo": "bar"}

    manager = _build_dialogue_manager()
    updated = await manager._handle_api_trigger(intent, state)

    assert updated.bot_message == [{"text": "Hello there"}, {"text": "Again"}]


@pytest.mark.asyncio
async def test_handle_api_trigger_with_api_success_renders_template_result() -> None:
    """API-backed intents should render their speech templates using the API payload."""
    api_details = ApiDetailsModel(
        url="https://example.com",
        request_type="POST",
        headers=[{"headerKey": "X-Test", "headerValue": "value"}],
    )
    intent = IntentModel(
        name="APICall",
        intent_id="api_call",
        speech_response="API says {{result.body.message}}",
        api_trigger=True,
        api_details=api_details,
    )
    state = State(thread_id="thread-6")
    state.context = {"scope": "test"}

    manager = _build_dialogue_manager()
    manager._call_intent_api = AsyncMock(
        return_value=HTTPResponse(status=200, body={"message": "hello"}, headers={})
    )

    updated = await manager._handle_api_trigger(intent, state)

    assert updated.bot_message == [{"text": "API says hello"}]
    manager._call_intent_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_api_trigger_api_failure_returns_service_unavailable_message() -> None:
    """Failures while calling a remote API should present a friendly fallback message."""
    api_details = ApiDetailsModel(
        url="https://example.com",
        request_type="POST",
        headers=[{"headerKey": "X-Test", "headerValue": "value"}],
    )
    intent = IntentModel(
        name="APICall",
        intent_id="api_call",
        speech_response="API says {{result.body.message}}",
        api_trigger=True,
        api_details=api_details,
    )
    state = State(thread_id="thread-7")

    manager = _build_dialogue_manager()
    manager._call_intent_api = AsyncMock(side_effect=DialogueManagerException("remote"))

    updated = await manager._handle_api_trigger(intent, state)

    assert updated.bot_message == [
        {"text": "Service is not available. Please try again later."}
    ]


@pytest.mark.asyncio
async def test_call_intent_api_constructs_json_payload_and_uses_headers() -> None:
    """API calls should render URLs, headers, and JSON payloads before invoking the client."""
    api_details = ApiDetailsModel(
        url="https://example.com/{{context.endpoint}}",
        request_type="POST",
        headers=[{"headerKey": "X-Test", "headerValue": "value"}],
        is_json=True,
        json_data="{\"payload\": \"{{parameters.value}}\"}",
    )
    intent = IntentModel(
        name="Trigger",
        intent_id="trigger",
        speech_response="Done",
        api_trigger=True,
        api_details=api_details,
    )
    current_state = State(thread_id="thread-8")
    current_state.context = {"endpoint": "v1"}
    current_state.extracted_parameters = {"value": "42"}

    fake_caller = FakeAPICaller(
        response=HTTPResponse(status=200, body={"ok": True}, headers={})
    )
    manager = _build_dialogue_manager(api_caller=fake_caller)

    await manager._call_intent_api(intent, current_state)

    assert fake_caller.called_args == (
        "https://example.com/v1",
        "POST",
        {"X-Test": "value"},
        {"payload": "42"},
        True,
    )


@pytest.mark.asyncio
async def test_call_intent_api_propagates_api_failures_as_dialogue_exceptions() -> None:
    """Transport failures should be wrapped as dialogue manager exceptions."""
    api_details = ApiDetailsModel(
        url="https://example.com",
        request_type="GET",
        headers=[],
    )
    intent = IntentModel(
        name="Trigger",
        intent_id="trigger",
        speech_response="Done",
        api_trigger=True,
        api_details=api_details,
    )
    current_state = State(thread_id="thread-9")

    fake_caller = FakeAPICaller(
        response=HTTPResponse(status=500, body={}, headers={}),
        should_raise=True,
    )
    manager = _build_dialogue_manager(api_caller=fake_caller)

    with pytest.raises(DialogueManagerException):
        await manager._call_intent_api(intent, current_state)

    assert fake_caller.called_args is not None