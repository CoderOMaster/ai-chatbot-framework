import pytest
from typing import Dict, Any

from app.bot.dialogue_manager.models import (
    ApiDetailsModel,
    ParameterModel,
    IntentModel,
    ChatModelBuilder,
    ChatModel,
    UserMessage,
)


class DummyApiDetails:
    def __init__(self, url=None, requestType=None, headers=None, isJson=None, jsonData=None):
        self.url = url
        self.requestType = requestType
        self.headers = headers
        self.isJson = isJson
        self.jsonData = jsonData


class DummyParam:
    def __init__(self, name=None, required=None, type=None, prompt=None):
        self.name = name
        self.required = required
        self.type = type
        self.prompt = prompt


class DummyIntent:
    def __init__(self, **kwargs):
        # allow arbitrary attributes
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def sample_api_headers() -> list:
    """Sample header list used by ApiDetailsModel.get_headers"""
    return [
        {"headerKey": "Authorization", "headerValue": "Bearer token"},
        {"headerKey": "Content-Type", "headerValue": "application/json"},
    ]


def test_api_details_get_headers(sample_api_headers: list) -> None:
    """ApiDetailsModel.get_headers should convert header list to dict correctly."""
    api = ApiDetailsModel(url="http://example", request_type="GET", headers=sample_api_headers, is_json=True, json_data='{}')
    headers = api.get_headers()
    assert headers["Authorization"] == "Bearer token"
    assert headers["Content-Type"] == "application/json"


def test_intent_from_db_success() -> None:
    """IntentModel.from_db maps fields from a DB intent object to domain model correctly."""
    api_details = DummyApiDetails(url="http://x", requestType="POST", headers=[{"headerKey": "A", "headerValue": "B"}], isJson=True, jsonData='{"k":1}')
    params = [DummyParam(name="p1", required=True, type="str", prompt="enter p1")]
    db_intent = DummyIntent(name="TestIntent", intentId="id123", speechResponse="hello", userDefined=False, apiTrigger=True, apiDetails=api_details, parameters=params)

    intent_model = IntentModel.from_db(db_intent)

    assert intent_model.name == "TestIntent"
    assert intent_model.intent_id == "id123"
    assert intent_model.speech_response == "hello"
    assert intent_model.user_defined is False
    assert intent_model.api_trigger is True
    assert isinstance(intent_model.api_details, ApiDetailsModel)
    assert intent_model.api_details.url == "http://x"
    assert len(intent_model.parameters) == 1
    assert intent_model.parameters[0].name == "p1"


def test_intent_from_db_none_raises() -> None:
    """Passing None to from_db should raise a ValueError."""
    with pytest.raises(ValueError) as exc:
        IntentModel.from_db(None)  # type: ignore
    assert "Database intent cannot be None" in str(exc.value)


def test_intent_from_db_missing_fields_raise() -> None:
    """Missing required name or intentId fields should raise ValueError with informative message."""
    db_intent_missing_name = DummyIntent(intentId="id")
    with pytest.raises(ValueError) as exc1:
        IntentModel.from_db(db_intent_missing_name)
    assert "Intent name is required" in str(exc1.value)

    db_intent_missing_id = DummyIntent(name="n")
    with pytest.raises(ValueError) as exc2:
        IntentModel.from_db(db_intent_missing_id)
    assert "Intent ID is required" in str(exc2.value)


def test_intent_from_db_invalid_api_details_structure_raises() -> None:
    """If apiDetails is of an invalid type that causes attribute access errors, a ValueError should be raised."""
    db_intent = DummyIntent(name="n", intentId="i", apiDetails=123)
    with pytest.raises(ValueError) as exc:
        IntentModel.from_db(db_intent)
    assert "Invalid API details structure" in str(exc.value)


def test_intent_from_db_invalid_parameters_structure_raises() -> None:
    """If parameters is not iterable (e.g., an int), from_db should raise a ValueError."""
    db_intent = DummyIntent(name="n", intentId="i", parameters=123)
    with pytest.raises(ValueError) as exc:
        IntentModel.from_db(db_intent)
    assert "Invalid parameters structure" in str(exc.value)


def test_chatmodel_from_json_success_and_to_json() -> None:
    """from_json should create a ChatModel and to_json should reflect the same data."""
    req = {
        "input": "hello",
        "context": {"a": 1},
        "intent": {"name": "X"},
        "extractedParameters": {"p": "v"},
        "missingParameters": ["p1"],
        "complete": True,
        "speechResponse": ["hi"],
        "currentNode": "n1",
        "parameters": [{"name": "p"}],
        "owner": "user1",
        "date": "2020-01-01T00:00:00Z",
    }
    chat = ChatModel.from_json(req)
    out = chat.to_json()
    assert out["input"] == "hello"
    assert out["context"]["a"] == 1
    assert out["intent"]["name"] == "X"
    assert out["extractedParameters"]["p"] == "v"
    assert out["missingParameters"] == ["p1"]
    assert out["complete"] is True
    assert out["speechResponse"] == ["hi"]
    assert out["currentNode"] == "n1"
    assert out["owner"] == "user1"
    assert out["date"] == "2020-01-01T00:00:00Z"


def test_chatmodel_from_json_invalid_types_raise() -> None:
    """from_json should validate input types and raise ValueError on mismatch."""
    with pytest.raises(ValueError):
        ChatModel.from_json([])  # not a dict

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": 123})  # input must be string

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": "x", "context": []})

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": "x", "context": {}, "intent": []})

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": "x", "context": {}, "intent": {}, "extractedParameters": []})

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": "x", "context": {}, "intent": {}, "extractedParameters": {}, "missingParameters": {}})

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": "x", "context": {}, "intent": {}, "extractedParameters": {}, "missingParameters": [], "speechResponse": {}})

    with pytest.raises(ValueError):
        ChatModel.from_json({"input": "x", "context": {}, "intent": {}, "extractedParameters": {}, "missingParameters": [], "speechResponse": [], "parameters": {}})


def test_chatmodel_clone_and_reset() -> None:
    """clone should return a deep copy and reset should restore default typed values."""
    chat = ChatModel(input_text="hi", context={"k": "v"}, speech_response=["r1"], current_node="n", parameters=[{"x": 1}], extracted_parameters={"a": 1}, missing_parameters=["m"], complete=True)
    cloned = chat.clone()

    # Ensure deep copy
    assert cloned is not chat
    assert cloned.context == chat.context
    cloned.context["k"] = "changed"
    assert chat.context["k"] == "v"

    # Reset should change types and values
    chat.reset()
    assert chat.complete is False
    assert chat.intent == {}
    assert chat.missing_parameters == []
    assert chat.extracted_parameters == {}
    assert chat.parameters == []
    assert chat.current_node == ""
    assert chat.speech_response == []


def test_chatmodel_builder_pattern() -> None:
    """ChatModelBuilder should build a ChatModel matching the provided fluent values."""
    builder = (
        ChatModelBuilder("hello")
        .with_context({"c": 1})
        .with_intent({"name": "I"})
        .with_extracted_parameters({"p": "v"})
        .with_missing_parameters(["m1"]) 
        .with_complete(True)
        .with_speech_response(["s"]) 
        .with_current_node("node1")
        .with_parameters([{"n": "p"}])
        .with_owner("owner1")
        .with_date("2021-01-01T00:00:00Z")
    )

    chat = builder.build()
    assert isinstance(chat, ChatModel)
    assert chat.input_text == "hello"
    assert chat.context == {"c": 1}
    assert chat.intent == {"name": "I"}
    assert chat.extracted_parameters == {"p": "v"}
    assert chat.missing_parameters == ["m1"]
    assert chat.complete is True
    assert chat.speech_response == ["s"]
    assert chat.current_node == "node1"
    assert chat.parameters == [{"n": "p"}]
    assert chat.owner == "owner1"
    assert chat.date == "2021-01-01T00:00:00Z"


def test_user_message_to_from_dict() -> None:
    """UserMessage.to_dict and from_dict should round-trip data including default channel."""
    um = UserMessage(thread_id="t1", text="hello", context={"a": 1})
    d = um.to_dict()
    assert d["thread_id"] == "t1"
    assert d["text"] == "hello"
    assert d["channel"] == "rest"
    assert d["context"]["a"] == 1

    um2 = UserMessage.from_dict({"thread_id": "t2", "text": "hi", "context": {"b": 2}})
    assert um2.thread_id == "t2"
    assert um2.text == "hi"
    assert um2.channel == "rest"
    assert um2.context == {"b": 2}