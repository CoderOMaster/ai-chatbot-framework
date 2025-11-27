from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, validator

from app.database import ObjectIdField


def _get_default_llm_api_key() -> Optional[str]:
    """Lazily load the LLM API key from application config if present.

    This avoids hardcoding sensitive defaults in the schema module and defers
    importing the application's configuration until a model instance is
    constructed.
    """
    try:
        from app.config import get_app_config

        config = get_app_config()
        return getattr(config, "LLM_API_KEY", None)
    except Exception:
        return None


class PipelineType(str, Enum):
    """Enumeration of supported NLU pipeline types."""

    TRADITIONAL = "traditional"
    LLM = "llm"


class TraditionalNLUSettings(BaseModel):
    """Settings for a traditional ML-based NLU pipeline."""

    intent_detection_threshold: float = 0.75
    entity_detection_threshold: float = 0.65
    use_spacy: bool = True


class LLMSettings(BaseModel):
    """Settings for an LLM-based NLU pipeline."""

    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: Optional[str] = Field(default_factory=_get_default_llm_api_key)
    model_name: str = "llama2:13b-chat"
    max_tokens: int = 4096
    temperature: float = 0.7


class NLUConfiguration(BaseModel):
    """Configuration for Natural Language Understanding.

    pipeline_type indicates which settings will be used. Use the PipelineType
    enum for clarity and validation.
    """

    pipeline_type: PipelineType = PipelineType.TRADITIONAL
    traditional_settings: TraditionalNLUSettings = Field(default_factory=TraditionalNLUSettings)
    llm_settings: LLMSettings = Field(default_factory=LLMSettings)

    class Config:
        use_enum_values = True


class Bot(BaseModel):
    """Base schema for bot configuration stored in the database.

    The MongoDB document id is aliased to `_id`. The id field is optional to
    ease creation flows prior to persistence. created_at and updated_at are
    normalized to timezone-aware datetimes (UTC) for consistent serialization.
    """

    id: Optional[ObjectIdField] = Field(default=None, alias="_id")
    name: str
    nlu_config: NLUConfiguration = Field(default_factory=NLUConfiguration)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @validator("created_at", "updated_at", pre=True, always=True)
    def _ensure_tzaware(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Ensure datetimes are timezone-aware (UTC)."""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    class Config:
        allow_population_by_field_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}