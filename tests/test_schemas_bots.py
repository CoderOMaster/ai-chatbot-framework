import os
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.admin.bots.schemas import (
    TraditionalNLUSettings,
    LLMSettings,
    NLUConfiguration,
    Bot,
)


@pytest.fixture(autouse=True)
def clear_env_llm_api_key(monkeypatch: Any) -> None:
    """Ensure LLM_API_KEY env var is not leaked between tests by clearing it by default.
    Individual tests can set it explicitly using monkeypatch.setenv.
    """
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    yield


def test_traditional_defaults() -> None:
    """Validate defaults for TraditionalNLUSettings are set and within expected ranges."""
    settings = TraditionalNLUSettings()
    assert settings.use_spacy is True
    assert isinstance(settings.intent_detection_threshold, float)
    assert 0.0 <= settings.intent_detection_threshold <= 1.0
    assert isinstance(settings.entity_detection_threshold, float)
    assert 0.0 <= settings.entity_detection_threshold <= 1.0


def test_traditional_valid_thresholds() -> None:
    """Custom valid thresholds should be accepted without raising errors."""
    settings = TraditionalNLUSettings(intent_detection_threshold=0.0, entity_detection_threshold=1.0)
    assert settings.intent_detection_threshold == 0.0
    assert settings.entity_detection_threshold == 1.0


@pytest.mark.parametrize("intent_val,entity_val", [(-0.1, 0.5), (0.5, 1.1), (2.0, -1.0)])
def test_traditional_invalid_thresholds(intent_val: float, entity_val: float) -> None:
    """Threshold values outside 0.0-1.0 should raise a ValidationError."""
    with pytest.raises(ValidationError):
        TraditionalNLUSettings(intent_detection_threshold=intent_val, entity_detection_threshold=entity_val)


def test_llm_defaults_and_env_fallback(monkeypatch: Any) -> None:
    """LLMSettings should use environment variable LLM_API_KEY when present and fallback to 'ollama' when not.

    This test checks both scenarios using monkeypatch.
    """
    # When env var is set
    monkeypatch.setenv("LLM_API_KEY", "envkey-123")
    settings_env = LLMSettings()
    assert settings_env.api_key == "envkey-123"

    # When env var is not set -> fallback to 'ollama'
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings_fallback = LLMSettings()
    assert settings_fallback.api_key == "ollama"

    # Base URL default
    assert settings_fallback.base_url == "http://127.0.0.1:11434/v1"
    # Model name default
    assert settings_fallback.model_name == "llama2:13b-chat"


@pytest.mark.parametrize("value", [1, 32768])
def test_llm_max_tokens_valid(value: int) -> None:
    """Valid boundary values for max_tokens should be accepted."""
    s = LLMSettings(max_tokens=value)
    assert s.max_tokens == value


@pytest.mark.parametrize("value", [0, 32769])
def test_llm_max_tokens_invalid(value: int) -> None:
    """max_tokens outside the allowed range should raise ValidationError."""
    with pytest.raises(ValidationError):
        LLMSettings(max_tokens=value)


@pytest.mark.parametrize("value", [0.0, 2.0])
def test_llm_temperature_valid(value: float) -> None:
    """Valid boundary values for temperature should be accepted."""
    s = LLMSettings(temperature=value)
    assert s.temperature == value


@pytest.mark.parametrize("value", [-0.1, 2.1])
def test_llm_temperature_invalid(value: float) -> None:
    """temperature outside the allowed range should raise ValidationError."""
    with pytest.raises(ValidationError):
        LLMSettings(temperature=value)


def test_nlu_configuration_pipeline_type_validation() -> None:
    """NLUConfiguration should accept only 'traditional' or 'llm' for pipeline_type."""
    cfg = NLUConfiguration(pipeline_type="llm")
    assert cfg.pipeline_type == "llm"

    with pytest.raises(ValidationError):
        NLUConfiguration(pipeline_type="hybrid")


def test_nlu_configuration_nested_llm_invalid() -> None:
    """If nested llm_settings contains invalid fields (e.g., max_tokens), NLUConfiguration creation should fail."""
    with pytest.raises(ValidationError):
        NLUConfiguration(llm_settings={"max_tokens": 0})


def test_bot_defaults_and_fields() -> None:
    """Bot should initialize with default NLU config and optional timestamps as None when not provided."""
    bot = Bot(name="TestBot")
    assert bot.name == "TestBot"
    assert bot.nlu_config is not None and isinstance(bot.nlu_config, NLUConfiguration)
    assert bot.created_at is None
    assert bot.updated_at is None
    # id should default to None (ObjectIdField wrapper is used in schema)
    assert bot.id is None


def test_bot_with_timestamps() -> None:
    """Bot should accept and retain provided datetime values for created_at and updated_at."""
    now = datetime.utcnow()
    bot = Bot(name="T", created_at=now, updated_at=now)
    assert bot.created_at == now
    assert bot.updated_at == now