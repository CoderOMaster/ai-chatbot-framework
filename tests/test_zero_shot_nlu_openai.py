import pytest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from app.bot.nlu.llm.zero_shot_nlu_openai import (
    LLMUnavailableError,
    ZeroShotNLUOpenAI,
    ZeroShotNLUOpenAISettings,
)


class DummyChain:
    """A simple callable chain to drive controlled responses for process()."""

    def __init__(self, result: dict | None = None, exception: Exception | None = None) -> None:
        self.result = result or {}
        self.exception = exception
        self.invocations: list[dict[str, str]] = []

    def invoke(self, payload: dict[str, str]) -> dict:
        self.invocations.append(payload)
        if self.exception:
            raise self.exception
        return self.result


@pytest.fixture
def component() -> ZeroShotNLUOpenAI:
    """Instantiate a component without invoking its constructor to keep dependencies isolated."""
    instance = ZeroShotNLUOpenAI.__new__(ZeroShotNLUOpenAI)
    instance.settings = ZeroShotNLUOpenAISettings()
    instance.intents = []
    instance.entities = []
    instance.llm = MagicMock()
    return instance


def test_build_llm_respects_settings_values() -> None:
    """Ensure _build_llm passes configured settings through to ChatOpenAI."""
    settings = ZeroShotNLUOpenAISettings(
        base_url="https://example.com",
        api_key="secret",
        model_name="custom-model",
        temperature=0.5,
        max_tokens=1234,
        request_timeout=30.0,
    )
    component = ZeroShotNLUOpenAI.__new__(ZeroShotNLUOpenAI)
    component.settings = settings

    with patch("app.bot.nlu.llm.zero_shot_nlu_openai.ChatOpenAI") as mock_chat_openai:
        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance
        llm = ZeroShotNLUOpenAI._build_llm(component)

    mock_chat_openai.assert_called_once_with(
        base_url="https://example.com",
        api_key="secret",
        model_name="custom-model",
        temperature=0.5,
        max_tokens=1234,
        request_timeout=30.0,
    )
    assert llm is mock_instance


def test_render_prompt_template_renders_data_from_intents_and_entities(component: ZeroShotNLUOpenAI) -> None:
    """Verify prompts are rendered using configured intents/entities and wrapped in a ChatPromptTemplate."""
    component.intents = ["OrderPizza"]
    component.entities = ["pizza_size"]

    template_mock = MagicMock()
    template_mock.render.return_value = "system prompt"

    environment_instance = MagicMock()
    environment_instance.get_template.return_value = template_mock

    prompt_template_instance = MagicMock()

    with patch("app.bot.nlu.llm.zero_shot_nlu_openai.Environment", return_value=environment_instance) as mock_env, \
        patch("app.bot.nlu.llm.zero_shot_nlu_openai.ChatPromptTemplate") as mock_chat_prompt:
        mock_chat_prompt.from_messages.return_value = prompt_template_instance
        prompt = ZeroShotNLUOpenAI._render_prompt_template(component)

    mock_env.assert_called_once()
    environment_instance.get_template.assert_called_once_with(component.PROMPT_TEMPLATE_NAME)
    template_mock.render.assert_called_once_with({"intents": component.intents, "entities": component.entities})
    mock_chat_prompt.from_messages.assert_called_once_with(
        [("system", "system prompt"), ("human", "{text}")]
    )
    assert prompt is prompt_template_instance


def test_process_no_text_message_returns_original(component: ZeroShotNLUOpenAI) -> None:
    """Messages without 'text' should bypass chain invocation and remain untouched."""
    dummy_chain = DummyChain(result={})
    component.chain = dummy_chain
    message = {"foo": "bar"}

    output = component.process(message)

    assert output is message
    assert message == {"foo": "bar"}
    assert dummy_chain.invocations == []


def test_process_populates_intent_and_filters_entities(component: ZeroShotNLUOpenAI) -> None:
    """Successful invocations should add intent payload, ranking, and strip empty entities."""
    result_payload = {
        "intent": "greet",
        "entities": {"location": "NYC", "unused": None},
    }
    dummy_chain = DummyChain(result=result_payload)
    component.chain = dummy_chain
    message = {"text": "hello"}

    output = component.process(message)

    assert output["intent"] == {"intent": "greet", "confidence": 1.0}
    assert output["intent_ranking"] == [output["intent"]]
    assert output["entities"] == {"location": "NYC"}
    assert dummy_chain.invocations == [{"text": "hello"}]


def test_process_handles_missing_intent_and_non_dict_entities(component: ZeroShotNLUOpenAI) -> None:
    """The component should default intents to None and treat non-dict entities as empty."""
    dummy_chain = DummyChain(result={"entities": ["unexpected"]})
    component.chain = dummy_chain
    message = {"text": "how are you"}

    output = component.process(message)

    assert output["intent"] == {"intent": None, "confidence": 0.0}
    assert output["entities"] == {}


def test_process_raises_llm_unavailable_error_when_chain_fails(component: ZeroShotNLUOpenAI) -> None:
    """Network/LLM faults should bubble up as LLMUnavailableError."""
    dummy_chain = DummyChain(exception=ValueError("down"))
    component.chain = dummy_chain
    message = {"text": "fail"}

    with pytest.raises(LLMUnavailableError):
        component.process(message)


def test_settings_rejects_request_timeout_below_minimum() -> None:
    """Confirm Pydantic enforces the minimum timeout constraint for request_timeout."""
    with pytest.raises(ValidationError):
        ZeroShotNLUOpenAISettings(request_timeout=0.5)