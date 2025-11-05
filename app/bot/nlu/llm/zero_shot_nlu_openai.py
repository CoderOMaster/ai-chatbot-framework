"""
Lightweight zero-shot NLU adapter that communicates with an OpenAI-compatible
LLM endpoint over HTTP. This refactor removes the heavy langchain dependency
from the core library and provides a small, testable classify(...) helper
that other parts of the application can call.

The original langchain-based implementation has been intentionally replaced
with a minimal HTTP client using `requests`. For heavy clients (langchain,
OpenAI SDK) consider packaging them in a Lambda Layer and using the lambda
handlers' `layer/requirements.txt`.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import jinja2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _build_prompt(text: str, intents: Optional[List[str]], entities: Optional[List[str]]) -> str:
    """Render the Jinja2 prompt template with provided intents/entities."""
    intents = intents or []
    entities = entities or []

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS_DIR))
    template = env.get_template(PROMPT_TEMPLATE_NAME)
    return template.render({"intents": intents, "entities": entities})


def _requests_session_with_retries(total_retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    """Create a requests Session configured with retry strategy."""
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def classify(
    text: str,
    intents: Optional[List[str]] = None,
    entities: Optional[List[str]] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    Classify text using an OpenAI-compatible HTTP endpoint.

    This function is intentionally small and dependency-light so it can be
    reused in Lambdas or other short-lived processes without pulling in
    langchain/openai SDKs.

    Returns a dict with keys: intent, intent_ranking, entities.
    """
    if not text:
        raise ValueError("`text` is required for classification")

    base_url = base_url or os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    model_name = model_name or os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")
    api_key = api_key or os.environ.get("LLM_API_KEY")

    system_prompt = _build_prompt(text, intents, entities)

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 1024,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        # Common pattern for OpenAI-compatible APIs
        headers["Authorization"] = f"Bearer {api_key}"

    session = _requests_session_with_retries()

    try:
        logger.debug("Sending request to LLM endpoint %s", base_url)
        resp = session.post(base_url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - network paths
        logger.exception("LLM request failed: %s", exc)
        return {"intent": None, "intent_ranking": [], "entities": {}}

    try:
        data = resp.json()
    except Exception:
        logger.exception("Failed to parse JSON response from LLM")
        return {"intent": None, "intent_ranking": [], "entities": {}}

    # Attempt to extract text content from common OpenAI-compatible shapes
    content = None
    if isinstance(data, dict):
        # OpenAI chat completion shape
        choices = data.get("choices") or []
        if choices and isinstance(choices, list):
            first = choices[0]
            # support both 'message' and 'text' variants
            if isinstance(first.get("message"), dict):
                content = first["message"].get("content")
            else:
                content = first.get("text")
        # Some local models might return `output` or direct `content`
        if content is None:
            content = data.get("output") or data.get("content")

    if not content:
        logger.warning("No textual content extracted from LLM response")
        return {"intent": None, "intent_ranking": [], "entities": {}}

    # The prompt requests strict JSON output. Attempt to parse it.
    try:
        parsed = json.loads(content.strip())
    except Exception:
        logger.exception("Failed to parse LLM content as JSON")
        return {"intent": None, "intent_ranking": [], "entities": {}}

    intent_value = parsed.get("intent")
    entities_out = parsed.get("entities") or {}

    intent = {"intent": intent_value, "confidence": 1.0} if intent_value else {"intent": None, "confidence": 0.0}
    intent_ranking = [intent] if intent_value else []

    return {"intent": intent, "intent_ranking": intent_ranking, "entities": entities_out}


# Backwards-compatible alias: some code paths called .process on component instances.
class ZeroShotNLUOpenAI:
    """Compatibility lightweight wrapper exposing process(message).

    Note: This is no longer a full NLUComponent subclass. It is a thin adapter
    for code that expects a .process(message) API.
    """

    def __init__(self, intents: Optional[List[str]] = None, entities: Optional[List[str]] = None, **kwargs):
        self.intents = intents or []
        self.entities = entities or []
        self.base_url = kwargs.get("base_url") or os.environ.get("LLM_BASE_URL")
        self.model_name = kwargs.get("model_name") or os.environ.get("LLM_MODEL_NAME")
        self.api_key = kwargs.get("api_key") or os.environ.get("LLM_API_KEY")

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        text = message.get("text")
        if not text:
            return message
        result = classify(
            text,
            intents=self.intents,
            entities=self.entities,
            base_url=self.base_url,
            model_name=self.model_name,
            api_key=self.api_key,
        )
        message["intent"] = result.get("intent")
        message["intent_ranking"] = result.get("intent_ranking")
        message["entities"] = result.get("entities")
        return message