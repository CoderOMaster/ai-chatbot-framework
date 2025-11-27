import os
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from app.database import ObjectIdField
from datetime import datetime


class TraditionalNLUSettings(BaseModel):
    """Settings for traditional ML-based NLU pipeline"""

    intent_detection_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for intent detection (0.0-1.0)"
    )
    entity_detection_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for entity detection (0.0-1.0)"
    )
    use_spacy: bool = Field(
        default=True,
        description="Whether to use spaCy for NLP processing"
    )

    @field_validator('intent_detection_threshold', 'entity_detection_threshold')
    @classmethod
    def validate_thresholds(cls, v: float) -> float:
        """Validate that thresholds are valid probabilities"""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")
        return v


class LLMSettings(BaseModel):
    """Settings for LLM-based NLU pipeline"""

    base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        description="Base URL for LLM API endpoint"
    )
    api_key: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "ollama"),
        description="API key for LLM service (defaults to LLM_API_KEY env var)"
    )
    model_name: str = Field(
        default="llama2:13b-chat",
        description="Name of the LLM model to use"
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=32768,
        description="Maximum tokens for LLM response"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM sampling (0.0-2.0)"
    )

    @field_validator('max_tokens')
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        """Validate that max_tokens is within acceptable range"""
        if v < 1 or v > 32768:
            raise ValueError("max_tokens must be between 1 and 32768")
        return v

    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate that temperature is within acceptable range"""
        if v < 0.0 or v > 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v


class NLUConfiguration(BaseModel):
    """Configuration for Natural Language Understanding"""

    pipeline_type: Literal["traditional", "llm"] = Field(
        default="traditional",
        description="Type of NLU pipeline: 'traditional' for ML-based or 'llm' for LLM-based"
    )
    traditional_settings: TraditionalNLUSettings = Field(
        default_factory=TraditionalNLUSettings,
        description="Settings for traditional ML-based NLU pipeline"
    )
    llm_settings: LLMSettings = Field(
        default_factory=LLMSettings,
        description="Settings for LLM-based NLU pipeline"
    )

    @field_validator('pipeline_type')
    @classmethod
    def validate_pipeline_type(cls, v: str) -> str:
        """Validate that pipeline_type is one of the supported types"""
        if v not in ("traditional", "llm"):
            raise ValueError("pipeline_type must be either 'traditional' or 'llm'")
        return v


class Bot(BaseModel):
    """Base schema for bot configuration"""

    id: ObjectIdField = Field(
        validation_alias="_id",
        default=None,
        description="Unique identifier for the bot"
    )
    name: str = Field(
        description="Name of the bot"
    )
    nlu_config: NLUConfiguration = Field(
        default_factory=NLUConfiguration,
        description="Natural Language Understanding configuration"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the bot was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the bot was last updated"
    )