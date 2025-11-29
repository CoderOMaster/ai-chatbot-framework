import pytest
from bson import ObjectId
from pydantic import ValidationError

from app.admin.bots.schemas import (
    Bot,
    LLMSettings,
    NLUConfiguration,
    PipelineType,
    TraditionalNLUSettings,
)


def test_pipeline_type_accepts_standard_modes() -> None:
    """Ensure that the new ML and zero-shot modes are recognized directly."""

    assert PipelineType("ml") == PipelineType.ML
    assert PipelineType("zero_shot") == PipelineType.ZERO_SHOT


def test_pipeline_type_supports_legacy_values() -> None:
    """Verify legacy pipeline mode identifiers are remapped to the new enum values."""

    assert PipelineType("traditional") == PipelineType.ML
    assert PipelineType("llm") == PipelineType.ZERO_SHOT
    assert PipelineType("LLM") == PipelineType.ZERO_SHOT  # case insensitivity
    assert PipelineType("  traditional  ") == PipelineType.ML  # trimming whitespace


def test_pipeline_type_invalid_value_raises() -> None:
    """An unsupported pipeline mode should raise ValueError so invalid configs are caught."""

    with pytest.raises(ValueError):
        PipelineType("unsupported")


def test_traditional_settings_defaults() -> None:
    """Check the default thresholds and spaCy flag for the traditional pipeline settings."""

    default_settings = TraditionalNLUSettings()

    assert default_settings.intent_detection_threshold == 0.75
    assert default_settings.entity_detection_threshold == 0.65
    assert default_settings.use_spacy


def test_llm_settings_require_api_key() -> None:
    """LLM settings must declare an api_key, otherwise validation should fail."""

    with pytest.raises(ValidationError):
        LLMSettings()


def test_llm_settings_accepts_configuration() -> None:
    """LLM settings should accept provided values and fall back to safe defaults."""

    settings = LLMSettings(api_key="super-secret")

    assert settings.api_key == "super-secret"
    assert settings.base_url == "http://127.0.0.1:11434/v1"
    assert settings.model_name == "llama2:13b-chat"
    assert settings.max_tokens == 4096
    assert settings.temperature == 0.7


def test_nlu_configuration_defaults_to_ml() -> None:
    """NLU configuration should default to the ML pipeline with safe traditional settings."""

    config = NLUConfiguration()

    assert config.pipeline_type == PipelineType.ML
    assert isinstance(config.traditional_settings, TraditionalNLUSettings)
    assert config.llm_settings is None


def test_nlu_configuration_can_enable_zero_shot() -> None:
    """It should be possible to configure the zero-shot pipeline with explicit LLM settings."""

    llm_settings = LLMSettings(api_key="another-secret")
    config = NLUConfiguration(
        pipeline_type=PipelineType.ZERO_SHOT,
        llm_settings=llm_settings,
    )

    assert config.pipeline_type == PipelineType.ZERO_SHOT
    assert config.llm_settings is llm_settings


def test_bot_default_configuration_and_dates() -> None:
    """Bot schema provides default NLU configuration and allows optional timestamps."""

    bot = Bot(name="assistant")

    assert bot.name == "assistant"
    assert bot.nlu_config.pipeline_type == PipelineType.ML
    assert bot.created_at is None
    assert bot.updated_at is None


def test_bot_respects_alias_and_provides_ids() -> None:
    """The Bot schema should accept the Mongo-style _id field via alias."""

    raw = {"_id": "507f1f77bcf86cd799439011", "name": "chatbot"}
    bot = Bot.model_validate(raw)

    assert str(bot.id) == raw["_id"]
    assert bot.name == "chatbot"
    assert bot.nlu_config.pipeline_type == PipelineType.ML