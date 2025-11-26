from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, SecretStr


class IntegrationSettings(BaseModel):
    """Settings container that prevents sensitive data leakage in logs/responses."""

    class Config:
        # Prevent accidental exposure of SecretStr values in string representations
        json_encoders = {SecretStr: lambda v: "***" if v else None}

    def dict(self, **kwargs) -> Dict[str, Any]:
        """Override dict to mask sensitive fields."""
        result = super().dict(**kwargs)
        # Mask any SecretStr fields in the output
        for key, value in result.items():
            if isinstance(value, SecretStr):
                result[key] = "***"
        return result

    def json(self, **kwargs) -> str:
        """Override json to mask sensitive fields."""
        kwargs.setdefault("exclude_unset", False)
        return super().json(**kwargs)


class IntegrationBase(BaseModel):
    """Base integration schema with secure settings handling."""

    id: str
    name: str
    description: str
    status: bool = False
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Integration settings - sensitive values should be stored as SecretStr",
    )

    class Config:
        json_encoders = {
            SecretStr: lambda v: "***" if v else None,
        }

    def dict(self, **kwargs) -> Dict[str, Any]:
        """Override dict to mask sensitive fields in settings."""
        result = super().dict(**kwargs)
        # Mask any SecretStr values in settings
        if "settings" in result and isinstance(result["settings"], dict):
            for key, value in result["settings"].items():
                if isinstance(value, SecretStr):
                    result["settings"][key] = "***"
        return result


class IntegrationCreate(IntegrationBase):
    """Schema for creating a new integration."""

    pass


class IntegrationUpdate(IntegrationBase):
    """Schema for updating an existing integration."""

    pass


class Integration(IntegrationBase):
    """Schema for retrieving integration data."""

    class Config:
        from_attributes = True
        json_encoders = {
            SecretStr: lambda v: "***" if v else None,
        }