import json
import logging
import os
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


# -------- Helpers --------

def _ok(body: Any) -> Dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _error(status: int, message: str) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


def _get_body(event: Dict[str, Any]) -> Dict[str, Any]:
    # API Gateway/Lambda proxy
    if "body" in event:
        body = event.get("body", "")
        if isinstance(body, dict):
            return body
        if event.get("isBase64Encoded"):
            import base64

            decoded = base64.b64decode(body or b"")
            return json.loads(decoded.decode("utf-8") or "{}")
        return json.loads((body or "").decode("utf-8") if isinstance(body, (bytes, bytearray)) else (body or "{}"))

    # Direct invoke
    return event


def _render_prompt(intents: List[str], entities: List[str]) -> str:
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
    env = Environment(loader=FileSystemLoader(prompts_dir))
    template = env.get_template("ZERO_SHOT_LEARNING_PROMPT.md")
    return template.render({"intents": intents, "entities": entities})


def _normalize_base_url(url: str) -> str:
    base = url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


# -------- LLM Calls --------

def _call_with_langchain(system_prompt: str, user_text: str, base_url: str, api_key: str, model_name: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
        from langchain_core.prompts import ChatPromptTemplate  # type: ignore
        from langchain_core.output_parsers import JsonOutputParser  # type: ignore
    except Exception as e:
        raise RuntimeError("LangChain/OpenAI layer is not available") from e

    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key or "not-need-for-local-models",
        model_name=model_name or "not-need-for-local-models",
        temperature=temperature,
        extra_body={"max_tokens": max_tokens},
    )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{text}"),
    ])

    chain = prompt_template | llm | JsonOutputParser()
    return chain.invoke({"text": user_text})


def _call_chat_completions_http(system_prompt: str, user_text: str, base_url: str, api_key: str, model_name: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
    # Minimal HTTP client using standard library only
    import urllib.request
    import urllib.error

    base = _normalize_base_url(base_url)
    url = base + "/v1/chat/completions"
    payload = {
        "model": model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    }
    data = json.dumps(payload).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    # Basic retry with backoff
    attempt = 0
    last_err: Optional[Exception] = None
    while attempt < 3:
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                resp_body = resp.read().decode("utf-8")
                data = json.loads(resp_body or "{}")
                content = (((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or ""
                return _parse_json_from_text(content)
        except Exception as e:  # noqa: PERF203 - small lambda
            last_err = e
            attempt += 1
            import time

            time.sleep(2 ** attempt * 0.5)
    raise RuntimeError(f"LLM HTTP call failed after retries: {last_err}")


def _parse_json_from_text(content: str) -> Dict[str, Any]:
    # Try to parse JSON strictly; fall back to extracting the first JSON object
    s = content.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            pass
    # Fallback minimal schema
    return {"intent": None, "entities": {}}


def _classify_zero_shot(text: str, intents: List[str], entities: List[str]) -> Dict[str, Any]:
    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    api_key = os.getenv("LLM_API_KEY", "")
    model_name = os.getenv("LLM_MODEL_NAME", "not-need-for-local-models")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))

    system_prompt = _render_prompt(intents, entities)

    # Prefer LangChain if available via layer; fallback to raw HTTP
    try:
        base_no_v1 = _normalize_base_url(base_url)
        return _call_with_langchain(system_prompt, text, base_no_v1, api_key, model_name, temperature, max_tokens)
    except Exception:
        logger.info("LangChain/OpenAI not available; falling back to raw HTTP chat completions")
        return _call_chat_completions_http(system_prompt, text, base_url, api_key, model_name, temperature, max_tokens)


# -------- Lambda Handler --------

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        payload = _get_body(event)
    except Exception:
        return _error(400, "Invalid JSON body")

    text = (payload or {}).get("text")
    if not text:
        return _error(400, "Missing 'text' in request body")

    intents = payload.get("intents") or []
    entities = payload.get("entities") or []

    try:
        result = _classify_zero_shot(text, intents, entities)
        # Normalize minimal schema
        intent_val = result.get("intent")
        entities_val = result.get("entities") or {}
        if intent_val is not None and not isinstance(intent_val, str):
            intent_val = str(intent_val)
        if not isinstance(entities_val, dict):
            entities_val = {}

        return _ok({"intent": intent_val, "entities": entities_val})
    except Exception as e:
        logger.exception("Zero-shot LLM handler error")
        return _error(500, f"Failed to classify: {e}")