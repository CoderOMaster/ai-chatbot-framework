import json
import os
import logging
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
except Exception:  # Layer may provide these at runtime
    ChatOpenAI = None  # type: ignore
    ChatPromptTemplate = None  # type: ignore
    JsonOutputParser = None  # type: ignore

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"
PROMPT_DIR = os.getenv("PROMPT_DIR", "app/bot/nlu/llm/prompts")


def _build_chain(intents: list[str], entities: list[str]):
    if ChatOpenAI is None or ChatPromptTemplate is None or JsonOutputParser is None:
        raise RuntimeError("LangChain/OpenAI libs not available. Ensure layer is attached.")

    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    api_key = os.getenv("LLM_API_KEY", "not-need-for-local-models")
    model_name = os.getenv("LLM_MODEL_NAME", "not-need-for-local-models")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))

    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        extra_body={"max_tokens": max_tokens},
    )

    env = Environment(loader=FileSystemLoader(PROMPT_DIR))
    template = env.get_template(PROMPT_TEMPLATE_NAME)
    system_prompt = template.render({"intents": intents, "entities": entities})

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{text}"),
    ])

    return prompt_template | llm | JsonOutputParser()


def handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    # Event contract: {"text": str, "intents": [..], "entities": [..]}
    body = event.get("body") if isinstance(event, dict) else None
    if isinstance(body, str):
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}
    elif isinstance(body, dict):
        payload = body
    else:
        payload = event if isinstance(event, dict) else {}

    text = payload.get("text")
    intents = payload.get("intents", [])
    entities = payload.get("entities", [])

    if not text:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing 'text' in request"}),
        }

    # Build chain per-invocation to remain stateless and avoid cold-start heavy state
    try:
        chain = _build_chain(intents, entities)
    except Exception as e:
        logger.exception("Initialization error")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    # Invoke with basic retry (idempotent forwarder)
    attempts = int(os.getenv("RETRY_ATTEMPTS", "2"))
    last_err: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            result = chain.invoke({"text": text})
            resp = {
                "intent": result.get("intent"),
                "entities": {k: v for k, v in (result.get("entities") or {}).items() if v is not None},
            }
            return {"statusCode": 200, "body": json.dumps(resp)}
        except Exception as e:
            logger.warning("LLM call failed, will retry if attempts remain: %s", e, exc_info=True)
            last_err = e

    return {
        "statusCode": 502,
        "body": json.dumps({"error": "LLM invocation failed", "details": str(last_err) if last_err else None}),
    }