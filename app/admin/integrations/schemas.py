from typing import Any, Dict

from pydantic import BaseModel, Field


IntegrationSettings = Dict[str, Any]
"""Configuration data for an integration; values may contain secrets that are masked."""


class IntegrationBase(BaseModel):
    """Represents the common schema for integration metadata exposed via the admin surface."""

    id: str
    name: str
    description: str
    status: bool = False
    settings: IntegrationSettings = Field(
        default_factory=dict,
        repr=False,
        description=(
            "Key/value configuration for the integration. "
            "Sensitive values are suppressed when the model renders."
        ),
    )


class IntegrationCreate(IntegrationBase):
    """Schema used when registering a new integration."""


class IntegrationUpdate(IntegrationBase):
    """Schema used when updating an existing integration."""


class Integration(IntegrationBase):
    """Schema used when loading an integration record from persistence."""

    class Config:
        from_attributes = True