import json
import logging
from typing import Any, Dict, List, Optional
from app.bot.nlu.pipeline import NLUComponent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


class ZeroShotNLUOpenAI(NLUComponent):
    """
    Zero-shot NLU component using an OpenAI-compatible LLM adapter to extract
    intents and entities.

    The LLM client may be injected for testing/mocking by passing ``llm`` to
    the constructor. If not provided, a ChatOpenAI instance will be created
    from kwargs.
    """

    PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        llm: Optional[Any] = None,
        prompt_dir: str = "app/bot/nlu/llm/prompts",
        **kwargs,
    ) -> None:
        """
        Initialize the zero-shot NLU component.

        Args:
            intents: List of intents to include in the system prompt.
            entities: List of entities to include in the system prompt.
            llm: Optional LLM client to use. If not provided a ChatOpenAI
                instance will be created using values from kwargs.
            prompt_dir: Directory containing the jinja2 prompt templates.
            **kwargs: Additional keyword args forwarded to the ChatOpenAI
                constructor when llm is not supplied.
        """
        self.intents = intents or []
        self.entities = entities or []

        # Allow dependency injection of LLM for easier testing/mocking. If
        # not provided, fall back to creating a ChatOpenAI instance.
        if llm is not None:
            self.llm = llm
        else:
            self.llm = ChatOpenAI(
                base_url=kwargs.get("base_url", "http://127.0.0.1:11434/v1"),
                api_key=kwargs.get("api_key", "not-need-for-local-models"),
                model_name=kwargs.get("model_name", "not-need-for-local-models"),
                temperature=kwargs.get("temperature", 0),
                extra_body={"max_tokens": kwargs.get("max_tokens", 4096)},
            )

        # Load and render the prompt template
        env = Environment(loader=FileSystemLoader(prompt_dir))
        template = env.get_template(self.PROMPT_TEMPLATE_NAME)
        self.system_prompt = template.render(
            {"intents": self.intents, "entities": self.entities}
        )

        # Define the prompt template used to construct the chain. We keep the
        # template/chain for backwards compatibility with existing LLMs that
        # expect a chain-like interface.
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.system_prompt), ("human", "{text}")]
        )

        # Use JsonOutputParser in the chain to maintain the expectation that
        # the model returns JSON. Consumers should be aware that malformed
        # JSON will now cause a hard failure (ValueError) instead of producing
        # partially populated intents.
        self.chain = prompt_template | self.llm | JsonOutputParser()

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Zero-shot component does not implement training."""
        return None

    def load(self, model_path: str) -> bool:
        """Zero-shot component has no model artifacts to load."""
        return True

    def _validate_parsed(self, parsed: Any) -> Dict[str, Any]:
        """
        Validate the parsed JSON-like object produced by the LLM. This
        enforces a minimal schema and will raise ValueError on malformed
        results to avoid returning partially populated intents.

        Expected minimum schema: {"intent": ..., "entities": {...}}
        """
        if not isinstance(parsed, dict):
            raise ValueError("LLM output is not a JSON object")

        if "intent" not in parsed:
            raise ValueError("LLM result missing 'intent' field")

        # Ensure entities exists and is a mapping (or empty dict)
        entities = parsed.get("entities", {})
        if entities is None:
            entities = {}
        if not isinstance(entities, dict):
            raise ValueError("LLM result 'entities' field is not an object")

        return {"intent": parsed.get("intent"), "entities": entities}

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a message through the zero-shot LLM to extract intent and
        entities.

        The method supports two invocation styles:
        - If the injected LLM implements a `stream(prompt, **kwargs)` method
          that yields string chunks, the response will be streamed and
          concatenated.
        - Otherwise the configured chain will be invoked synchronously.

        This method will raise ValueError if the LLM returns malformed JSON.
        """
        if not message.get("text"):
            logger.warning("Message does not contain 'text' key. Skipping processing.")
            return message

        text = message.get("text")

        # Prefer streaming if the LLM adapter exposes a `stream` generator.
        response_text: Optional[str] = None
        parsed_result: Optional[Any] = None

        try:
            if hasattr(self.llm, "stream") and callable(getattr(self.llm, "stream")):
                logger.debug("Using streaming LLM interface for text processing")
                chunks: List[str] = []
                for chunk in self.llm.stream(self.system_prompt, text=text):
                    # Expect chunk to be a string fragment
                    logger.debug("LLM stream chunk: %s", chunk)
                    chunks.append(str(chunk))
                response_text = "".join(chunks)
                # Try to parse streamed text as JSON
                parsed_result = json.loads(response_text)
            else:
                # Use the chain as previously configured. The chain.invoke may
                # return a dict-like object already parsed by JsonOutputParser.
                logger.debug("Invoking chain synchronously for text processing")
                result = self.chain.invoke({"text": text})

                # If the chain produced a mapping, use it. Otherwise try to
                # coerce to string and json-decode.
                if hasattr(result, "get"):
                    parsed_result = result
                else:
                    response_text = str(result)
                    parsed_result = json.loads(response_text)

            # Enforce strict schema validation and raise on malformed outputs
            validated = self._validate_parsed(parsed_result)

            intent_value = validated.get("intent")
            if intent_value:
                intent = {"intent": intent_value, "confidence": 1.0}
                message["intent"] = intent
                message["intent_ranking"] = [intent]
            else:
                message["intent"] = {"intent": None, "confidence": 0.0}
                message["intent_ranking"] = []

            entities = validated.get("entities", {})
            message["entities"] = {k: v for k, v in entities.items() if v is not None}

        except json.JSONDecodeError as e:
            # Malformed JSON from the model: fail loudly to avoid partial data
            logger.error("Malformed JSON returned by LLM: %s", e, exc_info=True)
            # Raise so callers/pipeline can detect the hard failure
            raise ValueError("Malformed JSON returned by LLM") from e
        except ValueError:
            # Re-raise validation errors after logging
            logger.exception("LLM returned invalid schema")
            raise
        except Exception as e:
            # For any other unexpected errors, log and return defaults but do
            # not mask the original exception in logs.
            logger.error("Error processing message with LLM: %s", e, exc_info=True)
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            message["entities"] = {}

        return message