from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, SecretStr, root_validator


class IntegrationSettings(BaseModel):
    """Flexible settings container for integrations.

    This model stores arbitrary key/value pairs but will automatically
    treat common secret keys (e.g. token, api_key, client_secret) as
    SecretStr so they are protected when inspected. Use masked() to
    obtain a safe representation for logs or UI.
    """

    __root__: Dict[str, Any] = Field(default_factory=dict)

    # keys that should be considered secrets (case-insensitive)
    SECRET_KEYS = {
        "token",
        "access_token",
        "secret",
        "api_key",
        "client_secret",
        "password",
    }

    @root_validator(pre=True)
    def _convert_known_secrets(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        # values may come in as the raw mapping or under the __root__ key
        data = values.get("__root__", values)
        converted: Dict[str, Any] = {}
        for k, v in (data or {}).items():
            if isinstance(k, str) and k.lower() in cls.SECRET_KEYS and v is not None:
                # wrap secret-like values with SecretStr to avoid accidental exposure
                converted[k] = SecretStr(str(v))
            else:
                converted[k] = v
        return {"__root__": converted}

    def masked(self) -> Dict[str, Any]:
        """Return a representation of settings with secrets masked.

        Values detected as secrets are replaced with a fixed mask ("*****")
        so this output is safe for logs and UI exposure.
        """
        output: Dict[str, Any] = {}
        for k, v in (self.__root__ or {}).items():
            if isinstance(v, SecretStr):
                # Do not reveal secret contents
                output[k] = "*****"
            else:
                output[k] = v
        return output


class IntegrationBase(BaseModel):
    """Base schema for an integration configuration.

    Keep this model free of persistence concerns so it can be reused across
    admin APIs and webhook/channel handlers. Use IntegrationSettings for
    the settings field to ensure secrets are handled safely.
    """

    id: str
    name: str
    description: Optional[str] = None
    status: bool = False
    settings: Optional[IntegrationSettings] = Field(default_factory=IntegrationSettings)

    class Config:
        # allow constructing from arbitrary objects/ORMs while keeping this
        # schema strictly focused on data representation
        from_attributes = True

    def masked(self) -> Dict[str, Any]:
        """Return a dict representation with any secret values masked.

        This is intended for safe logging or returning to clients where
        secrets must not be exposed.
        """
        base = self.dict()
        # settings may be IntegrationSettings or a dict; handle both
        settings = self.settings
        if isinstance(settings, IntegrationSettings):
            base["settings"] = settings.masked()
        elif isinstance(settings, dict):
            # best-effort masking for plain dicts
            base["settings"] = {
                k: ("*****" if k.lower() in IntegrationSettings.SECRET_KEYS else v)
                for k, v in settings.items()
            }
        else:
            base["settings"] = settings
        return base


class IntegrationCreate(IntegrationBase):
    """Schema used when creating an integration. Kept compatible with
    IntegrationBase for backward compatibility."""


class IntegrationUpdate(IntegrationBase):
    """Schema used when updating an integration. Kept compatible with
    IntegrationBase for backward compatibility."""


class Integration(IntegrationBase):
    """Full integration model used for responses.

    Uses from_attributes to allow construction from ORM objects or other
    attribute-based sources.
    """

    class Config(IntegrationBase.Config):
        pass