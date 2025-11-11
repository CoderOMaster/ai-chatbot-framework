import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

try:
    # Heavy clients should be provided via a Layer
    from langchain_openai import ChatOpenAI  # type: ignore
    from langchain_core.prompts import ChatPromptTemplate  # type: ignore
    from langchain_core.output_parsers import JsonOutputParser  # type: ignore
except Exception:  # pragma: no cover - layer may not be present in unit tests
    ChatOpenAI = None  # type: ignore
    ChatPromptTemplate = None  # type: ignore
    JsonOutputParser = None  # type: ignore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PROMPTS_DIR = os.environ.get(
    "PROMPTS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "app", "bot", "nlu", "llm", "prompts"),
)
PROMPT_TEMPLATE_NAME = os.environ.get("PROMPT_TEMPLATE_NAME", "ZERO_SHOT_LEARNING_PROMPT.md")
DEFAULT_TIMEOUT_SECS = int(os.environ.get("LLM_TIMEOUT_SECS", "25"))
MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
RETRY_BACKOFF_SECS = float(os.environ.get("LLM_RETRY_BACKOFF_SECS", "1.5"))


def _render_system_prompt(intents: List[str], entities: List[str]) -> str:
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    try:
        template = env.get_template(PROMPT_TEMPLATE_NAME)
    except TemplateNotFound as e:
        raise RuntimeError(f"Prompt template not found: {PROMPTS_DIR}/{PROMPT_TEMPLATE_NAME}") from e
    return template.render({"intents": intents, "entities": entities})


def _build_chain(intents: List[str], entities: List[str]):
    if ChatOpenAI is None:
        raise RuntimeError("LangChain/OpenAI client not available. Ensure layer is attached.")

    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    api_key = os.environ.get("LLM_API_KEY", "not-need-for-local-models")
    model_name = os.environ.get("LLM_MODEL_NAME", "not-need-for-local-models")
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "4096"))

    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        extra_body={"max_tokens": max_tokens},
        timeout=DEFAULT_TIMEOUT_SECS,
    )

    system_prompt = _render_system_prompt(intents, entities)
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{text}"),
    ])

    return prompt_template | llm | JsonOutputParser()


def _invoke_with_retries(chain, text: str) -> Dict[str, Any]:
    attempt = 0
    last_err: Optional[Exception] = None
    while attempt <= MAX_RETRIES:
        try:
            return chain.invoke({"text": text})
        except Exception as e:  # broad to catch SDK timeouts, HTTP errors, etc.
            last_err = e
            if attempt == MAX_RETRIES:
                break
            sleep_for = RETRY_BACKOFF_SECS * (2 ** attempt)
            logger.warning("LLM call failed (attempt %s/%s): %s; backing off %.2fs", attempt + 1, MAX_RETRIES + 1, e, sleep_for)
            time.sleep(sleep_for)
            attempt += 1
    raise RuntimeError(f"LLM invocation failed after {MAX_RETRIES + 1} attempts: {last_err}")


def _parse_result(result: Dict[str, Any]) -> Dict[str, Any]:
    # Result should already be JSON from JsonOutputParser
    intent_value = result.get("intent")
    if intent_value:
        intent = {"intent": intent_value, "confidence": 1.0}
        intent_ranking = [intent]
    else:
        intent = {"intent": None, "confidence": 0.0}
        intent_ranking = []
    entities = result.get("entities", {})
    if not isinstance(entities, dict):
        entities = {}
    entities = {k: v for k, v in entities.items() if v is not None}
    return {"intent": intent, "intent_ranking": intent_ranking, "entities": entities}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for zero-shot LLM classification.

    Event contract:
    {
      "text": "user input text",
      "intents": ["greet", "order_pizza"],
      "entities": ["size", "topping"]
    }
    """
    try:
        text = event.get("text")
        if not text:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required field: text"}),
            }
        intents = event.get("intents") or []
        entities = event.get("entities") or []
        if not isinstance(intents, list) or not isinstance(entities, list):
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "intents and entities must be lists"}),
            }

        chain = _build_chain(intents, entities)
        raw = _invoke_with_retries(chain, text)
        parsed = _parse_result(raw)
        return {"statusCode": 200, "body": json.dumps(parsed)}
    except Exception as e:
        logger.error("Error in zero-shot LLM handler: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "LLM handler error", "detail": str(e)}),
        }