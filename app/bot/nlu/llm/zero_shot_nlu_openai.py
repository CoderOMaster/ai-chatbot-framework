import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.bot.nlu.pipeline import MessagePayload, NLUComponent
from jinja2 import Environment, FileSystemLoader
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
PROMPTS_DIRECTORY = Path(__file__).resolve().parent / "prompts"


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM cannot be reached within the allotted timeout."""


class ZeroShotNLUOpenAISettings(BaseSettings):
    """Pydantic settings for configuring the OpenAI-compatible LLM used by the component."""

    base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        description="The OpenAI-compatible endpoint URL the component should use.",
    )
    api_key: str = Field(
        default="not-need-for-local-models",
        description="API key for authenticating with the OpenAI-compatible provider.",
    )
    model_name: str = Field(
        default="not-need-for-local-models",
        description="Model name routed via the OpenAI-compatible endpoint.",
    )
    temperature: float = Field(
        default=0.0,
        description="Sampling temperature used when invoking the model.",
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        description="Maximum number of tokens the LLM should emit per request.",
    )
    request_timeout: float = Field(
        default=20.0,
        ge=1.0,
        description="Timeout in seconds for each LLM invocation.",
    )

    class Config:
        env_prefix = "ZERO_SHOT_NLU_OPENAI_"
        env_file = ".env"


class ZeroShotNLUOpenAI(NLUComponent):
    """Zero-shot NLU component that renders a prompt template and extracts structured data."""

    PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        *,
        settings: Optional[ZeroShotNLUOpenAISettings] = None,
    ) -> None:
        """Construct the component and compile the Langchain prompt + LLM chain."""
        self.settings = settings or ZeroShotNLUOpenAISettings()
        self.intents = intents or []
        self.entities = entities or []
        self.llm = self._build_llm()
        prompt_template = self._render_prompt_template()
        self.chain = prompt_template | self.llm | JsonOutputParser()

    def _build_llm(self) -> ChatOpenAI:
        """Configure the ChatOpenAI instance with request timeout and token limits."""
        return ChatOpenAI(
            base_url=self.settings.base_url,
            api_key=self.settings.api_key,
            model_name=self.settings.model_name,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            request_timeout=self.settings.request_timeout,
        )

    def _render_prompt_template(self) -> ChatPromptTemplate:
        """Load and render the zero-shot learning prompt template for the LLM."""
        env = Environment(loader=FileSystemLoader(str(PROMPTS_DIRECTORY)))
        template = env.get_template(self.PROMPT_TEMPLATE_NAME)
        system_prompt = template.render({"intents": self.intents, "entities": self.entities})

        return ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{text}"),
            ]
        )

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:  # noqa: D401
        """Zero-shot NLU does not support training."""
        return None

    def load(self, model_path: str) -> bool:  # noqa: D401
        """Zero-shot NLU has no artifacts to load."""
        return True

    def process(self, message: MessagePayload) -> MessagePayload:
        """Invoke the LLM on the provided text and attach intents/entities to the message.

        Raises:
            LLMUnavailableError: When the configured LLM cannot be reached or times out.
        """
        text = message.get("text")
        if not text:
            logger.warning("Message does not contain 'text'. Skipping zero-shot processing.")
            return message

        try:
            result: Dict[str, Any] = self.chain.invoke({"text": text})
        except Exception as exc:  # pragma: no cover - best-effort guard for network/LLM failures
            logger.error("Failed to invoke the zero-shot LLM", exc_info=True)
            raise LLMUnavailableError("Unable to reach the configured LLM endpoint") from exc

        intent_value = result.get("intent")
        if intent_value:
            intent_payload = {"intent": intent_value, "confidence": 1.0}
            message["intent"] = intent_payload
            message["intent_ranking"] = [intent_payload]
        else:
            message["intent"] = {"intent": None, "confidence": 0.0}

        entities = result.get("entities", {})
        if isinstance(entities, dict):
            message["entities"] = {k: v for k, v in entities.items() if v is not None}
        else:
            message["entities"] = {}

        return message


__all__ = [
    "ZeroShotNLUOpenAI",
    "ZeroShotNLUOpenAISettings",
    "LLMUnavailableError",
]