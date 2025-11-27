import pytest
from pydantic import ValidationError, SecretStr

from app.admin.integrations import schemas


@pytest.fixture
def slack_settings_dict() -> dict:
    """Return a minimal valid Slack settings dict."""
    return {
        "webhook_url": "https://hooks.slack.com/services/T000/B000/XXX",
        "channel": "#alerts"
    }


def test_validate_integration_type_accepts_enum_and_case_insensitive_str():
    """IntegrationType validator should accept an enum value and case-insensitive strings."""
    # Using enum directly
    model_enum = schemas.IntegrationCreate(
        name="Slack Int",
        integration_type=schemas.IntegrationType.SLACK,
        settings={"webhook_url": "https://x", "channel": "#a"}
    )
    assert model_enum.integration_type == schemas.IntegrationType.SLACK

    # Using uppercase string (should be lowercased and accepted)
    model_str = schemas.IntegrationCreate(
        name="Slack Int 2",
        integration_type="SLACK",
        settings={"webhook_url": "https://x", "channel": "#a"}
    )
    assert model_str.integration_type == schemas.IntegrationType.SLACK


def test_validate_integration_type_invalid_string_raises():
    """Providing an unsupported integration_type string should raise a ValidationError."""
    with pytest.raises(ValidationError) as excinfo:
        schemas.IntegrationCreate(
            name="Bad",
            integration_type="not_a_type",
            settings={}
        )
    assert "Invalid integration type" in str(excinfo.value)


def test_validate_integration_type_non_string_raises():
    """Providing a non-string/non-enum integration_type should raise a ValidationError."""
    with pytest.raises(ValidationError) as excinfo:
        schemas.IntegrationCreate(
            name="Bad2",
            integration_type=123,
            settings={}
        )
    assert "Integration type must be a string" in str(excinfo.value)


def test_slack_settings_conversion_and_secrets(slack_settings_dict: dict):
    """When passing a dict for Slack settings, it should be converted to SlackSettings
    and secret fields should be SecretStr with correct secret value retrieval."""
    integration = schemas.IntegrationCreate(
        name="Prod Slack",
        integration_type="slack",
        settings=slack_settings_dict
    )

    # settings should be an instance of SlackSettings
    assert isinstance(integration.settings, schemas.SlackSettings)

    # webhook_url should be stored as SecretStr and return original via get_secret_value
    assert isinstance(integration.settings.webhook_url, SecretStr)
    assert integration.settings.webhook_url.get_secret_value() == slack_settings_dict["webhook_url"]
    assert integration.settings.channel == slack_settings_dict["channel"]


def test_slack_settings_missing_field_raises(slack_settings_dict: dict):
    """Missing required Slack settings fields should raise a ValidationError."""
    bad = slack_settings_dict.copy()
    bad.pop("webhook_url")

    with pytest.raises(ValidationError) as excinfo:
        schemas.IntegrationCreate(
            name="Prod Slack",
            integration_type="slack",
            settings=bad
        )
    # Should mention webhook_url is required
    assert "webhook_url" in str(excinfo.value)


def test_datadog_defaults_site_and_secrets():
    """Datadog settings should default the 'site' field and keep api/app keys as SecretStr."""
    dd_settings = {"api_key": "api-123", "app_key": "app-456"}
    integration = schemas.IntegrationCreate(
        name="Datadog",
        integration_type="datadog",
        settings=dd_settings
    )

    assert isinstance(integration.settings, schemas.DatadogSettings)
    assert integration.settings.site == "datadoghq.com"
    assert integration.settings.api_key.get_secret_value() == "api-123"
    assert integration.settings.app_key.get_secret_value() == "app-456"


def test_settings_passed_as_model_is_unchanged(slack_settings_dict: dict):
    """If settings are already a SlackSettings instance, the validator should not re-wrap them."""
    slack_model = schemas.SlackSettings(**slack_settings_dict)
    integration = schemas.IntegrationCreate(
        name="Slack Model",
        integration_type="slack",
        settings=slack_model
    )
    assert integration.settings is slack_model
    # Secret still accessible
    assert integration.settings.webhook_url.get_secret_value() == slack_settings_dict["webhook_url"]


def test_integration_update_accepts_partial_and_parses_settings(slack_settings_dict: dict):
    """IntegrationUpdate should accept partial fields and parse settings dict into the typed model."""
    update = schemas.IntegrationUpdate(
        name="New name",
        settings=slack_settings_dict
    )
    # settings should become SlackSettings even though IntegrationUpdate doesn't have the custom validator
    assert isinstance(update.settings, schemas.SlackSettings)
    assert update.settings.channel == slack_settings_dict["channel"]


def test_integration_requires_id_for_full_model(slack_settings_dict: dict):
    """Creating a full Integration requires an 'id' field; omission should raise a ValidationError."""
    with pytest.raises(ValidationError):
        # missing id
        schemas.Integration(
            name="Full",
            integration_type="slack",
            settings=slack_settings_dict
        )

    # Proper creation succeeds
    obj = schemas.Integration(
        id="int_1",
        name="Full",
        integration_type="slack",
        settings=slack_settings_dict
    )
    assert obj.id == "int_1"
    assert obj.integration_type == schemas.IntegrationType.SLACK