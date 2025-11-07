from fastapi import APIRouter, HTTPException, Request
from ai_chatbot_common.webhooks import forward_http_json, send_to_sqs
import os
import json

router = APIRouter(prefix="/rest", tags=["rest"])


def _get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


@router.post("/webbook")
async def webbook(request: Request):
    """
    Lightweight REST webhook adapter: accepts arbitrary JSON and forwards as a
    canonical UserMessage to an internal endpoint or SQS.
    """
    try:
        body_bytes = await request.body()
        payload = json.loads(body_bytes.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Canonicalize
    if not all(k in payload for k in ("thread_id", "text", "context")):
        thread_id = (
            payload.get("thread_id")
            or payload.get("sender_id")
            or payload.get("user")
            or "anonymous"
        )
        text = payload.get("text") or payload.get("message") or ""
        context = payload.get("context") or {
            k: v for k, v in payload.items() if k not in ("thread_id", "text", "message")
        }
        payload = {"thread_id": thread_id, "text": text, "context": context}

    try:
        forwarding_sqs = _get_env("FORWARDING_SQS_URL")
        forwarding_endpoint = _get_env("FORWARDING_ENDPOINT")
        if forwarding_sqs:
            send_to_sqs(forwarding_sqs, payload)
        else:
            headers = {"x-source": "rest-webhook"}
            forward_http_json(forwarding_endpoint or "", payload, headers=headers)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to forward message: {e}")