from __future__ import annotations

from typing import Any, Dict, Optional
from enum import Enum
import json
import base64

from pydantic import BaseModel, Field, field_serializer, field_validator


SENSITIVE_KEYS = {"secret", "page_access_token", "api_key", "token", "access_token"}


class IntegrationStatus(str, Enum):
    """Enum representing integration lifecycle state.

    This replaces the previous boolean flag for status while remaining
    tolerant of boolean inputs (True -> ACTIVE, False -> DISABLED) so
    existing stored documents with boolean values will continue to work.
    """

    ACTIVE = "active"
    DISABLED = "disabled"


def _get_cipher():
    """Lazily attempt to provide a Fernet cipher instance.

    If the cryptography package is not available or no key is configured,
    this returns None and the module falls back to a reversible base64
    encoded representation prefixed with "b64:". The Fernet key is read
    from app.config.get_app_config().INTEGRATION_ENCRYPTION_KEY when
    available.
    """
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except Exception:
        return None

    try:
        # lazy import to avoid circular imports at module import time
        from app.config import get_app_config

        cfg = get_app_config(raise_on_error=False)
        key = getattr(cfg, "INTEGRATION_ENCRYPTION_KEY", None)
    except Exception:
        key = None

    if not key:
        return None

    try:
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)
    except Exception:
        return None


def _encrypt_value(value: Any) -> str:
    """Encrypt or encode a single value for storage.

    Non-string values are JSON-serialized prior to encoding so types are
    preserved through the encode/decode cycle.
    """
    cipher = _get_cipher()
    raw = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    raw_bytes = raw.encode()

    if cipher is not None:
        token = cipher.encrypt(raw_bytes)
        return "fernet:" + token.decode()

    return "b64:" + base64.b64encode(raw_bytes).decode()


def _decrypt_value(stored: Any) -> Any:
    """Reverse of _encrypt_value. If the stored value is not a prefixed
    encoded string, return it unchanged.
    """
    if not isinstance(stored, str):
        return stored

    if stored.startswith("fernet:"):
        token = stored.split("fernet:", 1)[1]
        cipher = _get_cipher()
        if cipher is None:
            # Cannot decrypt without cipher; return token as-is to avoid data loss
            return token
        try:
            raw = cipher.decrypt(token.encode())
            raw_text = raw.decode()
        except Exception:
            return token
    elif stored.startswith("b64:"):
        payload = stored.split("b64:", 1)[1]
        try:
            raw_text = base64.b64decode(payload.encode()).decode()
        except Exception:
            return stored
    else:
        # not an encoded value
        return stored

    # attempt to load JSON to recover original types, fall back to str
    try:
        return json.loads(raw_text)
    except Exception:
        return raw_text


class IntegrationBase(BaseModel):
    """Base integration schema.

    - id, name, description are stored as plain strings.
    - status is an enum but the model accepts boolean inputs for
      backwards compatibility.
    - settings is a mapping that will have sensitive values encoded when the
      model is serialized (see field serializers below).
    """

    id: str
    name: str
    description: str
    status: IntegrationStatus = Field(default=IntegrationStatus.DISABLED)
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    def _coerce_bool_status(cls, v: Any) -> Any:
        """Allow legacy boolean status values to be accepted.

        True -> IntegrationStatus.ACTIVE, False -> IntegrationStatus.DISABLED.
        """
        if isinstance(v, bool):
            return IntegrationStatus.ACTIVE if v else IntegrationStatus.DISABLED
        return v

    @field_validator("settings", mode="before")
    def _decrypt_settings(cls, v: Any) -> Any:
        """When building a model from stored data, decrypt any encoded
        sensitive fields so the in-memory representation is plaintext for
        application use.
        """
        if not isinstance(v, dict):
            return v
        result: Dict[str, Any] = {}
        for key, val in v.items():
            if key in SENSITIVE_KEYS:
                result[key] = _decrypt_value(val)
            else:
                result[key] = val
        return result

    @field_serializer("settings", mode="after")
    def _encrypt_settings(self, v: Optional[Dict[str, Any]], _info) -> Optional[Dict[str, Any]]:
        """When serializing the model for storage, encode sensitive values.

        This keeps plaintext secrets out of the database while allowing the
        model instance used by the application to have convenient access to
        decrypted values.
        """
        if v is None:
            return v
        out: Dict[str, Any] = {}
        for key, val in v.items():
            if key in SENSITIVE_KEYS and val is not None:
                out[key] = _encrypt_value(val)
            else:
                out[key] = val
        return out


class IntegrationCreate(IntegrationBase):
    """Schema used when creating integrations."""


class IntegrationUpdate(IntegrationBase):
    """Schema used for updates. Keep from_attributes True to ease ORM
    population when reading results from the database drivers or ODMs.
    """

    class Config:
        from_attributes = True


class Integration(IntegrationBase):
    """Public representation returned by API endpoints."""

    class Config:
        from_attributes = True