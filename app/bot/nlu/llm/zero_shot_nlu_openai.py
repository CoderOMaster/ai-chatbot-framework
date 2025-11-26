"""Zero-shot NLU component using external LLM providers.

This module implements zero-shot intent and entity extraction using
configurable LLM endpoints (OpenAI, Ollama, or other compatible providers).
Configuration is externalized for flexibility across deployment environments.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseSettings, Field

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class LLMConfig(BaseSettings):
    """Configuration for LLM provider settings.
    
    Supports OpenAI-compatible endpoints (OpenAI, Ollama, etc.).
    Configuration can be loaded from environment variables or passed directly.
    """

    base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        description="Base URL for the LLM API endpoint",
        env="LLM_BASE_URL",
    )
    api_key: str = Field(
        default="not-need-for-local-models",
        description="API key for the LLM provider",
        env="LLM_API_KEY",
    )
    model_name: str = Field(
        default="llama2",
        description="Model name to use from the LLM provider",
        env="LLM_MODEL_NAME",
    )
    temperature: float = Field(
        default=0.0,
        description="Temperature for LLM response generation (0-1)",
        env="LLM_TEMPERATURE",
    )
    max_tokens: int = Field(
        default=4096,
        description="Maximum tokens in LLM response",
        env="LLM_MAX_TOKENS",
    )

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        case_sensitive = False


class LLMAdapter:
    """Adapter for LLM provider abstraction.
    
    Wraps LLM initialization to support multiple providers (OpenAI, Ollama, etc.)
    while maintaining a consistent interface. Currently implements OpenAI-compatible
    endpoints via langchain_openai.
    """

    def __init__(self, config: LLMConfig) -> None:
        """Initialize LLM adapter with configuration.
        
        Args:
            config: LLMConfig instance with provider settings.
        """
        self.config = config
        self.llm = self._initialize_llm()

    def _initialize_llm(self) -> ChatOpenAI:
        """Initialize the LLM client.
        
        Returns:
            ChatOpenAI: Initialized LLM client for OpenAI-compatible endpoints.
        """
        return ChatOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            model_name=self.config.model_name,
            temperature=self.config.temperature,
            extra_body={"max_tokens": self.config.max_tokens},
        )

    def get_llm(self) -> ChatOpenAI:
        """Get the initialized LLM client.
        
        Returns:
            ChatOpenAI: The LLM client instance.
        """
        return self.llm


class ZeroShotNLUOpenAI(NLUComponent):
    """Zero-shot NLU component using OpenAI-compatible LLM endpoints.
    
    Extracts intents and entities from text using zero-shot learning with
    an external LLM provider. Configuration is externalized for flexibility
    across containerized and local environments.
    """

    PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        llm_config: Optional[LLMConfig] = None,
        prompt_dir: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize zero-shot NLU component.
        
        Args:
            intents: List of intents to recognize. Defaults to empty list.
            entities: List of entities to extract. Defaults to empty list.
            llm_config: LLMConfig instance for provider settings.
                       If None, creates config from environment variables.
            prompt_dir: Directory path for prompt templates.
                       If None, uses default 'app/bot/nlu/llm/prompts'.
            **kwargs: Deprecated. Use llm_config parameter instead.
                     Kept for backwards compatibility.
        """
        self.intents = intents or []
        self.entities = entities or []

        # Initialize LLM configuration
        if llm_config is None:
            # Support legacy kwargs for backwards compatibility
            llm_config = LLMConfig(
                base_url=kwargs.get("base_url", "http://127.0.0.1:11434/v1"),
                api_key=kwargs.get("api_key", "not-need-for-local-models"),
                model_name=kwargs.get("model_name", "llama2"),
                temperature=kwargs.get("temperature", 0.0),
                max_tokens=kwargs.get("max_tokens", 4096),
            )

        # Initialize LLM adapter
        self.llm_adapter = LLMAdapter(llm_config)
        self.llm = self.llm_adapter.get_llm()

        # Determine prompt directory (support containerized environments)
        if prompt_dir is None:
            prompt_dir = os.getenv(
                "NLU_PROMPT_DIR",
                str(Path(__file__).parent / "prompts"),
            )

        # Load and render the prompt template
        self._load_prompt_template(prompt_dir)

        # Define the processing chain
        self.chain = self.prompt_template | self.llm | JsonOutputParser()

    def _load_prompt_template(self, prompt_dir: str) -> None:
        """Load and render the prompt template from file.
        
        Args:
            prompt_dir: Directory containing prompt template files.
            
        Raises:
            FileNotFoundError: If prompt template file is not found.
            jinja2.TemplateNotFound: If template cannot be loaded.
        """
        try:
            env = Environment(loader=FileSystemLoader(prompt_dir))
            template = env.get_template(self.PROMPT_TEMPLATE_NAME)
            system_prompt = template.render(
                {"intents": self.intents, "entities": self.entities}
            )

            self.prompt_template = ChatPromptTemplate.from_messages(
                [
                    ("system", system_prompt),
                    ("human", "{text}"),
                ]
            )
            logger.debug(
                f"Loaded prompt template from {prompt_dir}/{self.PROMPT_TEMPLATE_NAME}"
            )
        except Exception as e:
            logger.error(
                f"Failed to load prompt template from {prompt_dir}: {e}",
                exc_info=True,
            )
            raise

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Placeholder for training functionality.
        
        Zero-shot learning does not require training. This method is provided
        for interface compatibility with NLUComponent.
        
        Args:
            training_data: Training examples (unused for zero-shot).
            model_path: Path for model artifacts (unused for zero-shot).
        """
        pass

    def load(self, model_path: str) -> bool:
        """Placeholder for loading a pre-trained model.
        
        Zero-shot learning does not require loading a pre-trained model.
        This method is provided for interface compatibility with NLUComponent.
        
        Args:
            model_path: Path to model artifacts (unused for zero-shot).
            
        Returns:
            True: Always returns True as no loading is required.
        """
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and extract intents and entities.
        
        Uses the configured LLM endpoint to perform zero-shot extraction
        of intents and entities from the input text.
        
        Args:
            message: Input message dictionary containing 'text' key.
            
        Returns:
            Dict[str, Any]: Message enriched with 'intent', 'intent_ranking',
                           and 'entities' keys. On error, returns message with
                           empty/null values.
        """
        if not message.get("text"):
            logger.warning("Message does not contain 'text' key. Skipping processing.")
            return message

        try:
            result = self.chain.invoke({"text": message.get("text")})

            # Extract intent
            intent_value = result.get("intent")
            if intent_value:
                intent = {
                    "intent": intent_value,
                    "confidence": 1.0,
                }
                message["intent"] = intent
                message["intent_ranking"] = [intent]
            else:
                message["intent"] = {"intent": None, "confidence": 0.0}

            # Extract and filter entities
            entities = result.get("entities", {})
            message["entities"] = {k: v for k, v in entities.items() if v is not None}

        except Exception as e:
            logger.error(f"Error processing message with LLM: {e}", exc_info=True)
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            message["entities"] = {}

        return message