from __future__ import annotations

from typing import Any, Dict

import pytest

from app.bot.dialogue_manager.models import (
    ApiDetailsModel,
    ChatModel,
    IntentModel,
    ParameterModel,
    UserMessage,
)


class _DummyApiDetails:
    def __init__(self) -> None:
        self.url = "https://example.com"
        self.requestType = "POST"
        self.headers = [
            {"headerKey": "Content-Type", "headerValue": "application/json"},
            {"headerKey": "X-Request-ID", "headerValue": "123"},
        ]
        self.isJson = True
        self.jsonData = '{"flag": true}'


class _DummyParameter:
    def __init__(self, name: str, required: bool, type_: str, prompt: str) -> None:
        self.name = name
        self.required = required
        self.type = type_
        self.prompt = prompt


class _DummyIntent:
    def __init__(self) -> None:
        self.name = "greet"
        self.intentId = "intent-123"
        self.speechResponse = "Hello!"
        self.userDefined = True
        self.apiTrigger = True
        self.apiDetails = _DummyApiDetails()
        self.parameters = [
            _DummyParameter("location", True, "string", "Where are you?"),
            _DummyParameter("time", False, "string", "When?"),
        ]


@pytest.fixture
def sample_db_intent() -> _DummyIntent:
    """Provide a representative intent instance coming from the admin schema."""
    return _DummyIntent()


def test_api_details_get_headers_constructs_mapping() -> None:
    """Ensure ApiDetailsModel returns a dictionary keyed by header names."""
    api_details = ApiDetailsModel(
        url="https://example.com",
        request_type="POST",
        headers=[{"headerKey": "X-Test", "headerValue": "value"}],
        is_json=True,
        json_data="{}",
    )

    headers = api_details.get_headers()

    assert headers == {"X-Test": "value"}


def test_intent_from_db_translates_all_fields(sample_db_intent: _DummyIntent) -> None:
    """Verify that IntentModel.from_db maps every attribute from the admin model."""
    intent_model = IntentModel.from_db(sample_db_intent)

    assert intent_model.name == "greet"
    assert intent_model.intent_id == "intent-123"
    assert intent_model.speech_response == "Hello!"
    assert intent_model.user_defined is True
    assert intent_model.api_trigger is True
    assert intent_model.api_details is not None
    assert intent_model.api_details.url == "https://example.com"
    assert intent_model.parameters[0].name == "location"
    assert intent_model.parameters[1].prompt == "When?"


def test_intent_from_db_handles_missing_optional_sections() -> None:
    """Confirm that missing API details or parameters do not raise errors."""

    class _MinimalIntent:
        def __init__(self) -> None:
            self.name = "silent"
            self.intentId = "intent-000"
            self.speechResponse = ""
            self.userDefined = False
            self.apiTrigger = False
            self.apiDetails = None
            self.parameters = None

    minimal = _MinimalIntent()
    intent_model = IntentModel.from_db(minimal)  # type: ignore[arg-type]

    assert intent_model.api_details is None
    assert intent_model.parameters == []


def test_intent_model_parameters_default_list_is_unique() -> None:
    """Ensure default parameter lists are created per instance and not shared."""
    first_intent = IntentModel(name="a", intent_id="1", speech_response="ok")
    first_intent.parameters.append(ParameterModel(name="extra", required=False))
    second_intent = IntentModel(name="b", intent_id="2", speech_response="kaboom")

    assert second_intent.parameters == []


def test_chat_model_from_json_creates_expected_structure() -> None:
    """From_json should preserve each provided field and fill defaults for absent ones."""
    payload = {
        "input": "Hi",
        "context": {"foo": "bar"},
        "intent": {"name": "test"},
        "extractedParameters": {"a": 1},
        "missingParameters": ["b"],
        "complete": True,
        "speechResponse": ["Reply"],
        "currentNode": "start",
        "parameters": [{"name": "a"}],
        "owner": "tester",
        "date": "2024-01-01T00:00:00Z",
    }

    chat_model = ChatModel.from_json(payload)

    assert chat_model.input_text == "Hi"
    assert chat_model.context == {"foo": "bar"}
    assert chat_model.complete is True
    assert chat_model.date == "2024-01-01T00:00:00Z"


def test_chat_model_to_json_includes_all_fields() -> None:
    """To_json should reflect the chat model state accurately."""
    chat_model = ChatModel(
        input_text="Hi",
        context={"foo": "bar"},
        intent={"name": "test"},
        extracted_parameters={"a": 1},
        missing_parameters=["b"],
        complete=True,
        speech_response=["Reply"],
        current_node="start",
        parameters=[{"name": "a"}],
        owner="tester",
        date="2024-01-01T00:00:00Z",
    )

    serialized = chat_model.to_json()

    assert serialized["input"] == "Hi"
    assert serialized["missingParameters"] == ["b"]
    assert serialized["date"] == "2024-01-01T00:00:00Z"


def test_chat_model_clone_returns_deep_copy() -> None:
    """Clone should produce an independent instance protecting the original state."""
    chat_model = ChatModel(
        input_text="hello",
        context={"nested": [1, 2]},
        parameters=[{"a": 1}],
    )
    chat_clone = chat_model.clone()

    chat_clone.context["nested"].append(3)
    chat_clone.parameters[0]["a"] = 2

    assert chat_model.context["nested"] == [1, 2]
    assert chat_model.parameters[0]["a"] == 1


def test_chat_model_reset_clears_intent_specific_fields() -> None:
    """Reset should sanitize intent-tracking fields but preserve metadata like input_text."""
    chat_model = ChatModel(
        input_text="keep me",
        context={"foo": "bar"},
        intent={"name": "pending"},
        extracted_parameters={"p": 1},
        missing_parameters=["p"],
        complete=True,
        speech_response=["msg"],
        current_node="end",
        parameters=[{"name": "p"}],
        owner="owner-1",
    )

    chat_model.reset()

    assert chat_model.complete is False
    assert chat_model.intent == {}
    assert chat_model.missing_parameters == []
    assert chat_model.extracted_parameters == {}
    assert chat_model.parameters == []
    assert chat_model.current_node == ""
    assert chat_model.speech_response == []
    assert chat_model.input_text == "keep me"
    assert chat_model.owner == "owner-1"


def test_user_message_to_dict_returns_expected_payload() -> None:
    """Ensure serialization of UserMessage retains all declared fields."""
    user_message = UserMessage(thread_id="thread-1", text="hello", context={"foo": "bar"}, channel="test")

    serialized = user_message.to_dict()

    assert serialized == {
        "thread_id": "thread-1",
        "text": "hello",
        "channel": "test",
        "context": {"foo": "bar"},
    }


def test_user_message_from_dict_defaults_channel() -> None:
    """Deserialization should infer the default channel when it is missing."""
    payload: Dict[str, Any] = {
        "thread_id": "thread-2",
        "text": "hello",
        "context": {"foo": "bar"},
    }

    user_message = UserMessage.from_dict(payload)

    assert user_message.channel == "rest"
    assert user_message.thread_id == "thread-2"
    assert user_message.text == "hello"
    assert user_message.context == {"foo": "bar"}


def test_chat_model_default_date_is_isoformatted() -> None:
    """When no date is provided the model should still expose an ISO formatted timestamp."""
    chat_model = ChatModel(input_text="timestamp-test")

    assert isinstance(chat_model.date, str)
    assert chat_model.date.endswith("Z") or "+00:00" in chat_model.date