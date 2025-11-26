"""
Bot and NLU configuration schemas for the admin API.

This module defines Pydantic models for bot configuration, including
NLU pipeline settings (traditional ML and LLM-based). These schemas
are used for API request/response validation and configuration loading.
"""

from pydantic import BaseModel, Field
from typing import Optional
from app.database import ObjectIdField
from datetime import datetime


class TraditionalNLUSettings(BaseModel):
    """Settings for traditional ML-based NLU pipeline."""

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
        description="Whether to use spaCy for NLP preprocessing"
    )


class LLMSettings(BaseModel):
    """Settings for LLM-based NLU pipeline."""

    base_url: str = Field(
        description="Base URL for LLM API endpoint"
    )
    api_key: str = Field(
        description="API key for LLM service authentication (required, no default)"
    )
    model_name: str = Field(
        description="Name of the LLM model to use"
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        description="Maximum tokens for LLM response"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM sampling (0.0-2.0)"
    )


class NLUConfiguration(BaseModel):
    """Configuration for Natural Language Understanding pipeline."""

    pipeline_type: str = Field(
        default="traditional",
        pattern="^(traditional|llm)$",
        description="Type of NLU pipeline: 'traditional' or 'llm'"
    )
    traditional_settings: TraditionalNLUSettings = Field(
        default_factory=TraditionalNLUSettings,
        description="Settings for traditional ML-based NLU"
    )
    llm_settings: Optional[LLMSettings] = Field(
        default=None,
        description="Settings for LLM-based NLU (required if pipeline_type='llm')"
    )


class BotCreate(BaseModel):
    """Schema for creating a new bot (API request)."""

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Name of the bot"
    )
    nlu_config: NLUConfiguration = Field(
        default_factory=NLUConfiguration,
        description="NLU configuration for the bot"
    )


class BotUpdate(BaseModel):
    """Schema for updating an existing bot (API request)."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Name of the bot"
    )
    nlu_config: Optional[NLUConfiguration] = Field(
        default=None,
        description="NLU configuration for the bot"
    )


class Bot(BaseModel):
    """Schema for bot with database metadata (API response)."""

    id: ObjectIdField = Field(
        validation_alias="_id",
        description="MongoDB document ID"
    )
    name: str = Field(
        description="Name of the bot"
    )
    nlu_config: NLUConfiguration = Field(
        description="NLU configuration for the bot"
    )
    created_at: datetime = Field(
        description="Timestamp when the bot was created"
    )
    updated_at: datetime = Field(
        description="Timestamp when the bot was last updated"
    )

    class Config:
        """Pydantic model configuration."""
        populate_by_name = True