"""
AWS Lambda handler for zero-shot LLM forwarding. This handler accepts an
event with `text`, `intents`, and `entities` keys, calls the configured LLM
endpoint (LLM_BASE_URL) and returns the parsed JSON output.

Designed to be small and dependency-light. Heavy LLM SDKs (langchain, openai)
should be placed in a Lambda Layer (see lambda/handlers/llm/layer/requirements.txt).
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import jinja2

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"


def _build_prompt(text: str, intents: Optional[List[str]], entities: Optional[List[str]]) -> str:
    intents = intents or []
    entities = entities or []
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS_DIR))
    template = env.get_template(PROMPT_TEMPLATE_NAME)
    return template.render({"intents": intents, "entities": entities})


def _requests_session_with_retries(total_retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
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


def _call_llm(text: str, intents: Optional[List[str]], entities: Optional[List[str]]) -> Dict[str, Any]:
    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    model_name = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")
    api_key = os.environ.get("LLM_API_KEY")

    prompt = _build_prompt(text, intents, entities)

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 1024,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    session = _requests_session_with_retries()

    try:
        resp = session.post(base_url, json=payload, headers=headers, timeout=int(os.environ.get("LLM_TIMEOUT", "15")))
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.exception("LLM request failed")
        raise

    content = None
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices, list):
            first = choices[0]
            if isinstance(first.get("message"), dict):
                content = first["message"].get("content")
            else:
                content = first.get("text")
        if content is None:
            content = data.get("output") or data.get("content")

    if not content:
        raise ValueError("No content returned from LLM")

    return json.loads(content.strip())


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entry point.

    Expected event shape:
    {
      "text": "...",
      "intents": ["intent1", "intent2"],
      "entities": ["entity1", "entity2"]
    }

    Returns the parsed JSON object from the LLM.
    """
    logger.info("Invoked zero_shot LLM lambda with event: %s", event)

    text = event.get("text")
    intents = event.get("intents")
    entities = event.get("entities")

    if not text:
        return {"statusCode": 400, "body": json.dumps({"error": "`text` is required"})}

    try:
        parsed = _call_llm(text, intents, entities)
    except Exception as exc:
        logger.exception("Error calling LLM")
        return {"statusCode": 502, "body": json.dumps({"error": "LLM call failed", "details": str(exc)})}

    return {"statusCode": 200, "body": json.dumps(parsed)}