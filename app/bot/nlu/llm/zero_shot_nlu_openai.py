"""Zero-shot NLU component backed by an OpenAI-compatible LLM.

This module exposes ZeroShotNLUOpenAI which is configurable via
ZeroShotNLUSettings (a pydantic BaseSettings) so host services can inject
model_name, base_url and api_key from environment or application configuration.

LLM calls are guarded with a configurable timeout and surface a clear
LLMUnavailableError when the remote model is unreachable or slow so upstream
services can degrade gracefully.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import concurrent.futures

from pydantic import BaseSettings, Field
from jinja2 import Environment, FileSystemLoader

from app.bot.nlu.pipeline import NLUComponent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when the external LLM is unavailable or times out."""


class ZeroShotNLUSettings(BaseSettings):
    """Configuration for ZeroShotNLUOpenAI.

    These settings can be populated from environment variables by the host
    service or be constructed and injected directly when creating the
    component.
    """

    model_name: str = Field(..., env="ZERO_SHOT_MODEL_NAME")
    base_url: str = Field(..., env="ZERO_SHOT_BASE_URL")
    api_key: str = Field(..., env="ZERO_SHOT_API_KEY")
    temperature: float = 0.0
    max_tokens: int = 4096
    # How many seconds to wait for the LLM call before timing out
    request_timeout_seconds: int = 10


class ZeroShotNLUOpenAI(NLUComponent):
    """Zero-shot NLU component using an OpenAI-compatible LLM.

    Usage:
        settings = ZeroShotNLUSettings()
        comp = ZeroShotNLUOpenAI(intents=[...], entities=[...], settings=settings)

    For backward compatibility the constructor still accepts model configuration
    via keyword arguments (model_name, base_url, api_key) but this is
    discouraged in favor of injecting ZeroShotNLUSettings.
    """

    PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        settings: Optional[ZeroShotNLUSettings] = None,
        **kwargs,
    ) -> None:
        """Create the ZeroShotNLUOpenAI component.

        Args:
            intents: list of intent names the component should recognize.
            entities: list of entity names to extract.
            settings: optional ZeroShotNLUSettings object. If not provided the
                component will attempt to construct settings from environment
                variables. For backwards compatibility model settings may be
                provided via keyword args (model_name, base_url, api_key).
        """
        self.intents = intents or []
        self.entities = entities or []

        if settings is None:
            # If explicit kwargs were provided, allow them for backward
            # compatibility but prefer environment-backed settings.
            try:
                if any(k in kwargs for k in ("model_name", "base_url", "api_key")):
                    settings = ZeroShotNLUSettings(
                        model_name=kwargs.get("model_name"),
                        base_url=kwargs.get("base_url"),
                        api_key=kwargs.get("api_key"),
                        temperature=kwargs.get("temperature", 0.0),
                        max_tokens=kwargs.get("max_tokens", 4096),
                        request_timeout_seconds=kwargs.get("request_timeout_seconds", 10),
                    )
                else:
                    settings = ZeroShotNLUSettings()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Failed to build ZeroShotNLUSettings: %s", exc)
                raise

        self.settings = settings

        # Initialize the OpenAI LLM client
        self.llm = ChatOpenAI(
            base_url=self.settings.base_url,
            api_key=self.settings.api_key,
            model_name=self.settings.model_name,
            temperature=self.settings.temperature,
            extra_body={"max_tokens": self.settings.max_tokens},
        )

        # Load and render the prompt template
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        env = Environment(loader=FileSystemLoader(str(prompts_dir)))
        template = env.get_template(self.PROMPT_TEMPLATE_NAME)
        system_prompt = template.render({"intents": self.intents, "entities": self.entities})

        prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{text}"),
            ]
        )

        # Define the processing chain (prompt -> llm -> json parser)
        self.chain = prompt_template | self.llm | JsonOutputParser()

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Training is not applicable for zero-shot component; method kept to
        satisfy the NLUComponent interface.
        """
        return None

    def load(self, model_path: str) -> bool:
        """No model artifacts to load for zero-shot component. Returns True."""
        return True

    def _invoke_llm(self, text: str) -> Dict[str, Any]:
        """Invoke the assembled chain with a timeout.

        Raises:
            LLMUnavailableError: if the call times out or the underlying LLM
                client raises a network-related error.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.chain.invoke, {"text": text})
            try:
                return future.result(timeout=self.settings.request_timeout_seconds)
            except concurrent.futures.TimeoutError as te:
                future.cancel()
                logger.error("LLM request timed out after %s seconds", self.settings.request_timeout_seconds)
                raise LLMUnavailableError("LLM request timed out") from te
            except Exception as exc:
                logger.exception("LLM request failed: %s", exc)
                # Surface a clear, typed exception for upstream handling
                raise LLMUnavailableError("LLM request failed") from exc

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and extract intents and entities using the LLM.

        The component will raise LLMUnavailableError if the remote model is
        unavailable or the request times out. For parsing errors the component
        will log and return a message with empty/default predictions.
        """
        if not message.get("text"):
            logger.warning("Message does not contain 'text' key. Skipping processing.")
            return message

        try:
            result = self._invoke_llm(message.get("text"))

            # Extract intent
            intent_value = result.get("intent")
            if intent_value:
                intent = {"intent": intent_value, "confidence": 1.0}
                message["intent"] = intent
                message["intent_ranking"] = [intent]
            else:
                message["intent"] = {"intent": None, "confidence": 0.0}

            # Extract and filter entities
            entities = result.get("entities", {}) or {}
            # Keep only non-empty values
            message["entities"] = {k: v for k, v in entities.items() if v is not None}

        except LLMUnavailableError:
            # Propagate LLM availability issues to upstream callers so they can
            # decide how to degrade (fallback models, cached predictions, etc.)
            raise
        except Exception as e:
            logger.error("Error processing message with LLM: %s", e, exc_info=True)
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            message["entities"] = {}

        return message