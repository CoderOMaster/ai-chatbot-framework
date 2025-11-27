import json
import pytest
from bson import ObjectId

from app.admin.intents.schemas import (
    generate_object_id,
    LabeledSentences,
    Parameter,
    Intent,
)
from app.admin.intents.api_details import ApiDetails


@pytest.fixture
def valid_api_details() -> ApiDetails:
    """Return a valid ApiDetails instance for reuse in tests."""
    return ApiDetails(
        url="https://example.com/api",
        requestType="POST",
        headers=[{"headerKey": "Content-Type", "headerValue": "application/json"}],
        isJson=True,
        jsonData="{}",
    )


def test_generate_object_id_returns_valid_hex_string() -> None:
    """generate_object_id should return a 24-character hex string representing an ObjectId."""
    oid_str = generate_object_id()
    assert isinstance(oid_str, str)
    # Check length and that it is valid hex
    assert len(oid_str) == 24
    int(oid_str, 16)  # should not raise


def test_labeled_sentences_defaults_and_custom_id() -> None:
    """LabeledSentences should default to empty data list and auto-generate an ObjectId id.

    Also accepts custom data and id values (id provided as string is converted to ObjectId).
    """
    ls = LabeledSentences()
    assert isinstance(ls.data, list) and ls.data == []
    # id should be converted to a bson.ObjectId by the ObjectIdField annotation
    assert isinstance(ls.id, ObjectId)

    custom_data = ["hello world"]
    provided_id = str(ObjectId())
    ls2 = LabeledSentences(id=provided_id, data=custom_data)
    assert isinstance(ls2.id, ObjectId)
    assert str(ls2.id) == provided_id
    assert ls2.data == custom_data


def test_parameter_accepts_valid_types_case_insensitive() -> None:
    """Parameter.type should accept allowed types regardless of case and normalize to lowercase."""
    p = Parameter(name="param1", type="NUMBER")
    assert p.type == "number"

    p2 = Parameter(name="email_param", type="Email")
    assert p2.type == "email"


def test_parameter_rejects_invalid_type() -> None:
    """Providing an unsupported parameter type should raise a validation error."""
    with pytest.raises(ValueError):
        Parameter(name="p", type="not-a-type")


def test_parameter_name_validation_allows_expected_chars_and_rejects_others() -> None:
    """Parameter.name can contain alphanumerics, hyphens and underscores but not symbols like '!'."""
    Parameter(name="param_1", type="string")  # should not raise
    Parameter(name="param-name", type="string")  # should not raise

    with pytest.raises(ValueError):
        Parameter(name="bad!name", type="string")


def test_intent_name_validation_empty_and_too_long() -> None:
    """Intent.name must not be empty or whitespace-only and must be <= 255 chars."""
    with pytest.raises(ValueError):
        Intent(name="   ", intentId="id1", speechResponse="resp")

    long_name = "a" * 256
    with pytest.raises(ValueError):
        Intent(name=long_name, intentId="id1", speechResponse="resp")

    # valid trimmed name
    i = Intent(name="  My Intent  ", intentId="i1", speechResponse="ok")
    assert i.name == "My Intent"


def test_intent_id_validation_characters_and_trim() -> None:
    """Intent.intentId must only contain alphanumerics, hyphens and underscores; leading/trailing whitespace is stripped."""
    with pytest.raises(ValueError):
        Intent(name="A", intentId="bad id!", speechResponse="s")

    i = Intent(name="A", intentId="  good_id-1  ", speechResponse="s")
    assert i.intentId == "good_id-1"


def test_api_trigger_consistency_requires_api_details_when_trigger_true(valid_api_details: ApiDetails) -> None:
    """When apiTrigger is True, apiDetails must be provided; otherwise a validation error occurs."""
    # Missing apiDetails while apiTrigger True
    with pytest.raises(ValueError):
        Intent(name="A", intentId="a1", speechResponse="s", apiTrigger=True)

    # Providing apiDetails with apiTrigger True should succeed
    i = Intent(name="A", intentId="a1", speechResponse="s", apiTrigger=True, apiDetails=valid_api_details)
    assert i.apiTrigger is True
    assert isinstance(i.apiDetails, ApiDetails)


def test_api_trigger_consistency_rejects_api_details_when_trigger_false(valid_api_details: ApiDetails) -> None:
    """When apiTrigger is False, providing apiDetails should raise a validation error."""
    with pytest.raises(ValueError):
        Intent(name="A", intentId="a1", speechResponse="s", apiTrigger=False, apiDetails=valid_api_details)


def test_intent_with_invalid_nested_parameter_raises() -> None:
    """If one of the nested Parameter entries is invalid, Intent construction should fail."""
    bad_param = {"name": "bad!name", "type": "string"}
    with pytest.raises(ValueError):
        Intent(name="HasBadParam", intentId="p1", speechResponse="r", parameters=[bad_param])


def test_intent_defaults_and_collections() -> None:
    """Intent should initialize collection fields with defaults when not provided."""
    i = Intent(name="DefaultCollections", intentId="c1", speechResponse="ok")
    assert isinstance(i.parameters, list) and i.parameters == []
    assert isinstance(i.labeledSentences, list) and i.labeledSentences == []
    assert isinstance(i.trainingData, list) and i.trainingData == []