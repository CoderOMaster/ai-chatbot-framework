from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.types import ObjectIdField


class TraditionalNLUSettings(BaseModel):
    """Settings for traditional ML-based NLU pipeline"""

    intent_detection_threshold: float = 0.75
    entity_detection_threshold: float = 0.65
    use_spacy: bool = True


class LLMSettings(BaseModel):
    """Settings for LLM-based NLU pipeline"""

    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: str = Field(..., description="API key used to authenticate to the configured LLM provider")
    model_name: str = "llama2:13b-chat"
    max_tokens: int = 4096
    temperature: float = 0.7


class PipelineType(str, Enum):
    """Enumerates supported NLU pipeline modes."""

    ML = "ml"
    ZERO_SHOT = "zero_shot"

    @classmethod
    def _missing_(cls, value: object) -> "PipelineType":
        legacy_mapping = {
            "traditional": cls.ML,
            "llm": cls.ZERO_SHOT,
        }
        if isinstance(value, str):
            normalized = value.lower().strip()
            legacy_value = legacy_mapping.get(normalized)
            if legacy_value is not None:
                return legacy_value
        return super()._missing_(value)


class NLUConfiguration(BaseModel):
    """Configuration for Natural Language Understanding"""

    pipeline_type: PipelineType = Field(default=PipelineType.ML)
    traditional_settings: TraditionalNLUSettings = Field(
        default_factory=TraditionalNLUSettings
    )
    llm_settings: Optional[LLMSettings] = Field(
        default=None, description="Settings for LLM-backed zero-shot pipelines"
    )


class Bot(BaseModel):
    """Base schema for bot"""

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str
    nlu_config: NLUConfiguration = Field(default_factory=NLUConfiguration)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None