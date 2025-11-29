import pytest
from pydantic import ValidationError

from app.admin.integrations.schemas import Integration, IntegrationBase


@pytest.fixture
def base_payload() -> dict[str, str]:
    """Provides a minimal payload for creating integration schema instances."""
    return {
        "id": "integration-123",
        "name": "Example Integration",
        "description": "Used for testing purposes",
    }


def test_integration_base_defaults_status_and_settings(base_payload: dict[str, str]) -> None:
    """Ensure that new IntegrationBase instances default status to False and have an empty settings dict."""
    integration = IntegrationBase(**base_payload)

    assert integration.status is False
    assert isinstance(integration.settings, dict)
    assert integration.settings == {}


def test_integration_settings_default_factory_is_independent(base_payload: dict[str, str]) -> None:
    """Verify that each IntegrationBase instance receives an isolated settings dictionary by default."""
    first = IntegrationBase(**base_payload)
    first.settings["api_key"] = "secret"

    second = IntegrationBase(**base_payload)

    assert second.settings == {}


def test_integration_settings_repr_masks_sensitive_values(base_payload: dict[str, str]) -> None:
    """Confirm sensitive settings values are suppressed from the model's string representation."""
    payload = {
        **base_payload,
        "settings": {"SUPER_SECRET": "dont_log_me"},
    }
    integration = IntegrationBase(**payload)
    representation = repr(integration)

    assert "dont_log_me" not in representation
    assert "settings" not in representation


def test_integration_model_validate_accepts_attribute_based_objects() -> None:
    """Validate that Integration can be created from attribute-based objects thanks to from_attributes config."""

    class AttributeRecord:
        def __init__(self) -> None:
            self.id = "attr-987"
            self.name = "Attribute Source"
            self.description = "Loaded from a non-dict source"
            self.status = True
            self.settings = {"token": "value"}

    record = AttributeRecord()
    integration = Integration.model_validate(record)

    assert integration.id == record.id
    assert integration.name == record.name
    assert integration.description == record.description
    assert integration.status is True
    assert integration.settings == record.settings


def test_integration_base_missing_required_fields_raises_validation_error() -> None:
    """Ensure required metadata fields are enforced by the schema validation."""
    with pytest.raises(ValidationError):
        IntegrationBase(id="missing-name", description="no name provided")