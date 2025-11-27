from typing import Any, Dict, List
from types import SimpleNamespace
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import get_dialogue_manager
from app.bot.dialogue_manager.dialogue_manager import DialogueManager, DialogueManagerException

router = APIRouter(prefix="/rest", tags=["rest"])


class RestUserMessage(BaseModel):
    """Pydantic DTO for incoming REST messages.

    This decouples the public HTTP contract from internal DialogueManager
    dataclasses and enables validation and sanitization of the context.
    """

    thread_id: str = Field(..., alias="thread_id")
    text: str
    context: Dict[str, Any] = Field(default_factory=dict)


def _sanitize_value(value: Any) -> Any:
    """Sanitize a single value so it's JSON-serializable and safe to persist.

    - Primitive types are kept as-is.
    - dict/list are recursively sanitized.
    - other types are converted to str to avoid leaking internal objects.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return _sanitize_dict(value)
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    # Fallback: convert unknown objects to their string representation
    try:
        return str(value)
    except Exception:
        return None


def _sanitize_dict(d: Dict[Any, Any]) -> Dict[str, Any]:
    """Return a sanitized shallow copy of a mapping with str keys and sanitized values."""
    result: Dict[str, Any] = {}
    for k, v in d.items():
        try:
            key = str(k)
        except Exception:
            key = "<invalid_key>"
        result[key] = _sanitize_value(v)
    return result


@router.post("/webbook")
async def webbook(body: RestUserMessage, dialogue_manager: DialogueManager = Depends(get_dialogue_manager)):
    """Endpoint to converse with the chatbot.

    The request body is validated by RestUserMessage. The context is sanitized
    to avoid leaking internal objects or non-JSON-serializable values. The
    response is streamed as newline-delimited JSON (NDJSON) so callers can
    start receiving bot messages as soon as they are produced.
    """
    # Sanitize context before handing it to the dialogue manager
    sanitized_context = _sanitize_dict(body.context)

    # Build a lightweight message object compatible with DialogueManager's expectations
    message_obj = SimpleNamespace(thread_id=body.thread_id, text=body.text, context=sanitized_context, channel="rest")

    try:
        new_state = await dialogue_manager.process(message_obj)
    except DialogueManagerException as e:
        # Convert internal DialogueManager errors to HTTP 400 with a proper 'detail'.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Unhandled exceptions -> 500
        raise HTTPException(status_code=500, detail="Internal server error")

    bot_messages: List[Dict[str, Any]] = getattr(new_state, "bot_message", []) or []

    def _ndjson_generator() -> bytes:
        # Stream each message as a JSON line to reduce latency for multi-message replies
        for m in bot_messages:
            try:
                chunk = json.dumps(m, ensure_ascii=False)
            except Exception:
                # Last resort: stringify the message
                chunk = json.dumps({"text": str(m)})
            yield (chunk + "\n").encode("utf-8")

    return StreamingResponse(_ndjson_generator(), media_type="application/x-ndjson")