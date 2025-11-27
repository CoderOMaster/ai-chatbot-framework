from enum import Enum
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field, field_validator, SecretStr


class IntegrationStatus(str, Enum):
    """Integration status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"


class IntegrationType(str, Enum):
    """Supported integration types."""
    SLACK = "slack"
    GITHUB = "github"
    JIRA = "jira"
    DATADOG = "datadog"
    PAGERDUTY = "pagerduty"


class SlackSettings(BaseModel):
    """Slack integration settings."""
    webhook_url: SecretStr = Field(..., description="Slack webhook URL")
    channel: str = Field(..., description="Default channel for notifications")
    
    class Config:
        json_schema_extra = {
            "example": {
                "webhook_url": "https://hooks.slack.com/services/...",
                "channel": "#alerts"
            }
        }


class GitHubSettings(BaseModel):
    """GitHub integration settings."""
    token: SecretStr = Field(..., description="GitHub personal access token")
    repository: str = Field(..., description="Repository in format owner/repo")
    
    class Config:
        json_schema_extra = {
            "example": {
                "token": "ghp_...",
                "repository": "owner/repo"
            }
        }


class JiraSettings(BaseModel):
    """Jira integration settings."""
    url: str = Field(..., description="Jira instance URL")
    username: str = Field(..., description="Jira username")
    api_token: SecretStr = Field(..., description="Jira API token")
    project_key: str = Field(..., description="Default Jira project key")
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://company.atlassian.net",
                "username": "user@company.com",
                "api_token": "ATATT...",
                "project_key": "PROJ"
            }
        }


class DatadogSettings(BaseModel):
    """Datadog integration settings."""
    api_key: SecretStr = Field(..., description="Datadog API key")
    app_key: SecretStr = Field(..., description="Datadog application key")
    site: str = Field(default="datadoghq.com", description="Datadog site (datadoghq.com or datadoghq.eu)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "...",
                "app_key": "...",
                "site": "datadoghq.com"
            }
        }


class PagerDutySettings(BaseModel):
    """PagerDuty integration settings."""
    integration_key: SecretStr = Field(..., description="PagerDuty integration key")
    api_token: SecretStr = Field(..., description="PagerDuty API token")
    
    class Config:
        json_schema_extra = {
            "example": {
                "integration_key": "...",
                "api_token": "..."
            }
        }


# Union type for all integration settings
IntegrationSettings = Union[
    SlackSettings,
    GitHubSettings,
    JiraSettings,
    DatadogSettings,
    PagerDutySettings,
    Dict[str, Any]  # Fallback for custom integrations
]


class IntegrationBase(BaseModel):
    """Base integration model."""
    name: str = Field(..., min_length=1, max_length=255, description="Integration name")
    description: str = Field(default="", max_length=1000, description="Integration description")
    integration_type: IntegrationType = Field(..., description="Type of integration")
    status: IntegrationStatus = Field(default=IntegrationStatus.INACTIVE, description="Integration status")
    settings: IntegrationSettings = Field(..., description="Integration-specific settings")
    
    @field_validator("integration_type", mode="before")
    @classmethod
    def validate_integration_type(cls, v: Any) -> IntegrationType:
        """Validate integration type is supported."""
        if isinstance(v, IntegrationType):
            return v
        if isinstance(v, str):
            try:
                return IntegrationType(v.lower())
            except ValueError:
                valid_types = ", ".join([t.value for t in IntegrationType])
                raise ValueError(f"Invalid integration type. Must be one of: {valid_types}")
        raise ValueError("Integration type must be a string")
    
    @field_validator("settings", mode="before")
    @classmethod
    def validate_settings(cls, v: Any, info) -> IntegrationSettings:
        """Validate settings based on integration type."""
        if not isinstance(v, dict):
            return v
        
        integration_type = info.data.get("integration_type")
        if not integration_type:
            return v
        
        # Map integration types to their settings models
        settings_map = {
            IntegrationType.SLACK: SlackSettings,
            IntegrationType.GITHUB: GitHubSettings,
            IntegrationType.JIRA: JiraSettings,
            IntegrationType.DATADOG: DatadogSettings,
            IntegrationType.PAGERDUTY: PagerDutySettings,
        }
        
        settings_model = settings_map.get(integration_type)
        if settings_model:
            return settings_model(**v)
        
        return v


class IntegrationCreate(IntegrationBase):
    """Schema for creating a new integration."""
    pass


class IntegrationUpdate(BaseModel):
    """Schema for updating an integration."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Integration name")
    description: Optional[str] = Field(None, max_length=1000, description="Integration description")
    status: Optional[IntegrationStatus] = Field(None, description="Integration status")
    settings: Optional[IntegrationSettings] = Field(None, description="Integration-specific settings")


class Integration(IntegrationBase):
    """Complete integration model with ID."""
    id: str = Field(..., description="Integration unique identifier")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "int_123abc",
                "name": "Production Slack",
                "description": "Slack notifications for production alerts",
                "integration_type": "slack",
                "status": "active",
                "settings": {
                    "webhook_url": "https://hooks.slack.com/services/...",
                    "channel": "#alerts"
                }
            }
        }