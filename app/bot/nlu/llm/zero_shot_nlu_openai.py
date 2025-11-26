import logging
from typing import Any, Dict, List, Optional
from functools import lru_cache
from tenacity import retry, stop_after_attempt, wait_exponential
from shared.nlu.pipeline import NLUComponent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


class ZeroShotNLUOpenAI(NLUComponent):
    """
    Zero-shot NLU component using OpenAI compatible language model API to extract intents and entities.
    Includes retry logic, caching, and configurable timeouts for Lambda deployment.
    """

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        prompt_template_path: str = "app/bot/nlu/llm/prompts",
        prompt_template_name: str = "ZERO_SHOT_LEARNING_PROMPT.md",
        request_timeout: int = 30,
        max_retries: int = 3,
        **kwargs,
    ):
        """
        Args:
            intents (Optional[List[str]]): List of intents to recognize.
            entities (Optional[List[str]]): List of entities to extract.
            prompt_template_path (str): Path to prompt templates directory.
            prompt_template_name (str): Name of the prompt template file.
            request_timeout (int): Timeout in seconds for LLM API calls.
            max_retries (int): Maximum number of retries for failed API calls.
            **kwargs: Additional arguments for OpenAI configuration.
        """
        self.intents = intents or []
        self.entities = entities or []
        self.prompt_template_path = prompt_template_path
        self.prompt_template_name = prompt_template_name
        self.request_timeout = request_timeout
        self.max_retries = max_retries

        # Initialize the OpenAI LLM with timeout
        self.llm = ChatOpenAI(
            base_url=kwargs.get("base_url", "http://127.0.0.1:11434/v1"),
            api_key=kwargs.get("api_key", "not-need-for-local-models"),
            model_name=kwargs.get("model_name", "not-need-for-local-models"),
            temperature=kwargs.get("temperature", 0),
            request_timeout=request_timeout,
            extra_body={"max_tokens": kwargs.get("max_tokens", 4096)},
        )

        # Load and render the prompt template
        self.chain = self._build_chain()

    @lru_cache(maxsize=128)
    def _get_cached_prompt(self, intents_tuple: tuple, entities_tuple: tuple) -> str:
        """
        Cache rendered prompts for repeated intent/entity configurations.

        Args:
            intents_tuple (tuple): Tuple of intents for caching.
            entities_tuple (tuple): Tuple of entities for caching.

        Returns:
            str: Rendered system prompt.
        """
        env = Environment(loader=FileSystemLoader(self.prompt_template_path))
        template = env.get_template(self.prompt_template_name)
        system_prompt = template.render(
            {"intents": list(intents_tuple), "entities": list(entities_tuple)}
        )
        return system_prompt

    def _build_chain(self):
        """
        Build the LLM processing chain with cached prompt.

        Returns:
            Runnable: The LangChain processing chain.
        """
        intents_tuple = tuple(self.intents)
        entities_tuple = tuple(self.entities)
        system_prompt = self._get_cached_prompt(intents_tuple, entities_tuple)

        prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{text}"),
            ]
        )

        return prompt_template | self.llm | JsonOutputParser()

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """
        Placeholder for training functionality. Not implemented for zero-shot learning.
        """
        pass

    def load(self, model_path: str) -> bool:
        """
        Placeholder for loading a pre-trained model. Not implemented for zero-shot learning.
        """
        return True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _invoke_chain(self, text: str) -> Dict[str, Any]:
        """
        Invoke the LLM chain with retry logic for transient failures.

        Args:
            text (str): The input text to process.

        Returns:
            Dict[str, Any]: The parsed LLM response.

        Raises:
            Exception: If all retry attempts fail.
        """
        return self.chain.invoke({"text": text})

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a message and extract intents and entities using the OpenAI model.

        Args:
            message (Dict[str, Any]): The input message containing the text to process.

        Returns:
            Dict[str, Any]: The processed message with extracted intents and entities.
        """
        if not message.get("text"):
            logger.warning("Message does not contain 'text' key. Skipping processing.")
            return message

        try:
            result = self._invoke_chain(message.get("text"))

            # Extract intent
            intent_value = result.get("intent")
            if intent_value:
                intent = {
                    "intent": intent_value,
                    "confidence": 1.0,  # Zero-shot models don't provide confidence scores
                }
                message["intent"] = intent
                message["intent_ranking"] = [intent]  # Single intent in ranking
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