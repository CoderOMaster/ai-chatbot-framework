"""
Bot configuration schemas for NLU pipeline management.

Provides Pydantic models for bot configuration including NLU settings,
traditional ML-based and LLM-based pipeline configurations.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from shared.database import ObjectIdField


class TraditionalNLUSettings(BaseModel):
    """Settings for traditional ML-based NLU pipeline.
    
    Attributes:
        intent_detection_threshold: Confidence threshold for intent detection (0.0-1.0).
        entity_detection_threshold: Confidence threshold for entity detection (0.0-1.0).
        use_spacy: Whether to use spaCy for NLP processing.
    """

    intent_detection_threshold: float = 0.75
    entity_detection_threshold: float = 0.65
    use_spacy: bool = True

    @field_validator("intent_detection_threshold", "entity_detection_threshold")
    @classmethod
    def validate_threshold_range(cls, v: float) -> float:
        """Validate that threshold values are between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")
        return v

    model_config = {"json_schema_extra": {"example": {"intent_detection_threshold": 0.75, "entity_detection_threshold": 0.65, "use_spacy": True}}}


class LLMSettings(BaseModel):
    """Settings for LLM-based NLU pipeline.
    
    Attributes:
        base_url: Base URL for LLM API endpoint.
        api_key: API key for authentication.
        model_name: Name of the LLM model to use.
        max_tokens: Maximum number of tokens in response.
        temperature: Temperature parameter for response generation (0.0-1.0).
    """

    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: str = "ollama"
    model_name: str = "llama2:13b-chat"
    max_tokens: int = 4096
    temperature: float = 0.7

    @field_validator("temperature")
    @classmethod
    def validate_temperature_range(cls, v: float) -> float:
        """Validate that temperature is between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Temperature must be between 0.0 and 1.0")
        return v

    model_config = {"json_schema_extra": {"example": {"base_url": "http://127.0.0.1:11434/v1", "api_key": "ollama", "model_name": "llama2:13b-chat", "max_tokens": 4096, "temperature": 0.7}}}


class NLUConfiguration(BaseModel):
    """Configuration for Natural Language Understanding pipeline.
    
    Supports both traditional ML-based and LLM-based NLU approaches.
    The pipeline_type determines which settings are actively used.
    
    Attributes:
        pipeline_type: Type of NLU pipeline ('traditional' or 'llm').
        traditional_settings: Configuration for traditional ML pipeline.
        llm_settings: Configuration for LLM-based pipeline.
    """

    pipeline_type: str = "traditional"
    traditional_settings: TraditionalNLUSettings = Field(default_factory=TraditionalNLUSettings)
    llm_settings: LLMSettings = Field(default_factory=LLMSettings)

    @field_validator("pipeline_type")
    @classmethod
    def validate_pipeline_type(cls, v: str) -> str:
        """Validate that pipeline_type is either 'traditional' or 'llm'."""
        if v not in ("traditional", "llm"):
            raise ValueError("pipeline_type must be either 'traditional' or 'llm'")
        return v

    model_config = {"json_schema_extra": {"example": {"pipeline_type": "traditional", "traditional_settings": {"intent_detection_threshold": 0.75, "entity_detection_threshold": 0.65, "use_spacy": True}, "llm_settings": {"base_url": "http://127.0.0.1:11434/v1", "api_key": "ollama", "model_name": "llama2:13b-chat", "max_tokens": 4096, "temperature": 0.7}}}}


class Bot(BaseModel):
    """Base schema for bot configuration.
    
    Attributes:
        id: MongoDB ObjectId identifier.
        name: Bot name.
        nlu_config: NLU pipeline configuration.
        created_at: Timestamp of bot creation.
        updated_at: Timestamp of last bot update.
    """

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str
    nlu_config: NLUConfiguration = Field(default_factory=NLUConfiguration)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"json_schema_extra": {"example": {"_id": "507f1f77bcf86cd799439011", "name": "example_bot", "nlu_config": {"pipeline_type": "traditional"}, "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"}}}