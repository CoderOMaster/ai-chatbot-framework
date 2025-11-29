import pytest
from bson import ObjectId
from pydantic import ValidationError

from app.admin.intents.schemas import (
    ApiDetails,
    Intent,
    LabeledSentences,
    Parameter,
)


@pytest.fixture
def header_entries() -> list[dict[str, str]]:
    """Provide a shared list of header definitions for API-related tests."""
    return [
        {"headerKey": "Authorization", "headerValue": "Bearer token"},
        {"headerKey": "Accept", "headerValue": "application/json"},
    ]


def test_labeledsentences_defaults_are_not_shared() -> None:
    """Ensure the default data list is not shared between instances and id defaults to None."""
    first = LabeledSentences()
    second = LabeledSentences()

    first.data.append("user input")

    assert first.id is None
    assert first.data == ["user input"]
    assert second.data == []
    assert second.id is None


def test_parameter_defaults_and_required_fields() -> None:
    """Validate default parameter values and that the name field is required."""
    param = Parameter(name="some_parameter")

    assert param.id is None
    assert param.required is False
    assert param.type is None
    assert param.prompt is None

    with pytest.raises(ValidationError):
        Parameter()


def test_api_details_get_headers_returns_mapping(header_entries: list[dict[str, str]]) -> None:
    """Confirm headers are transformed into a dict keyed by headerKey."""
    details = ApiDetails(
        url="https://example.com",
        requestType="POST",
        headers=header_entries,
    )

    assert details.get_headers() == {
        "Authorization": "Bearer token",
        "Accept": "application/json",
    }


def test_api_details_get_headers_handles_duplicate_keys(
    header_entries: list[dict[str, str]]
) -> None:
    """Verify that later header entries overwrite earlier ones with the same key."""
    header_entries.append({"headerKey": "Accept", "headerValue": "application/xml"})
    details = ApiDetails(
        url="https://example.com",
        requestType="POST",
        headers=header_entries,
    )

    result = details.get_headers()

    assert result["Accept"] == "application/xml"
    assert result["Authorization"] == "Bearer token"


def test_api_details_get_headers_with_missing_keys_raises_key_error() -> None:
    """Ensure missing headerKey or headerValue entries raise a KeyError during header extraction."""
    details = ApiDetails(
        url="https://example.com",
        requestType="GET",
        headers=[{"headerKey": "X-Custom"}, {"headerValue": "value"}],
    )

    with pytest.raises(KeyError):
        details.get_headers()


def test_intent_accepts_aliases_and_nested_id_defaults() -> None:
    """Intent should accept an _id alias and leave nested IDs unset unless provided."""
    identifier = ObjectId()
    intent = Intent(
        _id=identifier,
        name="book_flight",
        intentId="book_flight",
        speechResponse="Sure, where to?",
    )

    assert intent.id == identifier
    assert intent.parameters == []
    assert intent.labeledSentences == []


def test_intent_additional_fields_can_be_populated() -> None:
    """Populate every optional intent subfield to ensure they are accepted by the schema."""
    intent = Intent(
        _id=ObjectId(),
        name="test",
        intentId="test",
        speechResponse="done",
        apiTrigger=True,
        apiDetails=ApiDetails(
            url="https://example.com",
            requestType="POST",
            headers=[{"headerKey": "k", "headerValue": "v"}],
        ),
        parameters=[Parameter(name="p1")],
        labeledSentences=[LabeledSentences(data=["hello"])],
        trainingData=[{"data": "value"}],
    )

    assert intent.apiTrigger is True
    assert intent.apiDetails is not None
    assert intent.parameters[0].name == "p1"
    assert intent.labeledSentences[0].data == ["hello"]
    assert intent.trainingData == [{"data": "value"}]