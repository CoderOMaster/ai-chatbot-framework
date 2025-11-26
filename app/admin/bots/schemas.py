from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator

# Prefer a central Core ID type when available so bot configs can be stored
# in different datastores in the future. Fall back to the DB-specific
# ObjectIdField for backwards compatibility.
try:
    from app.core.types import ID as CoreID  # type: ignore
except Exception:
    from app.database import ObjectIdField as CoreID  # type: ignore


class TraditionalNLUSettings(BaseModel):
    """Settings for traditional ML-based NLU pipeline."""

    intent_detection_threshold: float = 0.75
    entity_detection_threshold: float = 0.65
    use_spacy: bool = True


class LLMSettings(BaseModel):
    """Settings for LLM-based NLU pipeline.

    NOTE: api_key must not be hard-coded in code. It should be provided
    from configuration or a secrets manager at runtime. This model does
    not provide a default API key.
    """

    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: Optional[str] = None
    model_name: str = "llama2:13b-chat"
    max_tokens: int = 4096
    temperature: float = 0.7


class NLUConfiguration(BaseModel):
    """Configuration for Natural Language Understanding.

    pipeline_type supports 'ml' and 'zero_shot' to match pipeline_utils. For
    backwards compatibility this model will also accept the older values
    'traditional' -> 'ml' and 'llm' -> 'zero_shot'. The validator normalizes
    those legacy values to the canonical ones.
    """

    pipeline_type: str = "ml"  # canonical values: 'ml', 'zero_shot'
    traditional_settings: TraditionalNLUSettings = Field(default_factory=TraditionalNLUSettings)
    llm_settings: LLMSettings = Field(default_factory=LLMSettings)

    @validator("pipeline_type", pre=True)
    def _normalize_pipeline_type(cls, v: str) -> str:
        """Normalize legacy pipeline type names and validate value."""
        if not isinstance(v, str):
            raise ValueError("pipeline_type must be a string")
        mapping = {"traditional": "ml", "llm": "zero_shot"}
        normalized = mapping.get(v, v)
        allowed = {"ml", "zero_shot"}
        if normalized not in allowed:
            raise ValueError(f"pipeline_type must be one of {sorted(list(allowed))}, got '{v}'")
        return normalized


class Bot(BaseModel):
    """Declarative schema for bot configuration shared between admin and runtime.

    The `id` field uses a CoreID type when available; otherwise it falls back
    to the legacy ObjectIdField. Timestamps are optional and managed by the
    storage layer.
    """

    id: CoreID = Field(validation_alias="_id", default=None)
    name: str
    nlu_config: NLUConfiguration = Field(default_factory=NLUConfiguration)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None