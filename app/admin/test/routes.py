from typing import Any, Optional
import asyncio

from fastapi import APIRouter, Depends, HTTPException
import aiohttp

from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager, DialogueManagerClient

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/chat")
async def chat(
    body: dict, dialogue_manager: Optional[DialogueManagerClient] = Depends(get_dialogue_manager)
) -> Any:
    """
    Thin proxy endpoint that forwards a constructed UserMessage to the
    external dialogue-manager-service and returns the raw response.

    The endpoint expects a JSON body containing at least 'thread_id' and
    'text'. The optional 'context' field will be forwarded as-is.
    """

    if dialogue_manager is None:
        raise HTTPException(status_code=503, detail="dialogue-manager service unavailable")

    user_message = UserMessage(
        thread_id=body.get("thread_id", ""),
        text=body.get("text", ""),
        context=body.get("context", {}) or {},
    )

    try:
        # Forward the message to the remote dialogue-manager service. The
        # client returns decoded JSON when possible, otherwise raw text.
        result = await dialogue_manager.request("POST", "/process", json=user_message.to_dict())
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="dialogue-manager request timed out")
    except aiohttp.ClientError as e:
        # Surface transport/client errors only; application-level errors
        # are returned by the remote service and forwarded as-is.
        raise HTTPException(status_code=502, detail=str(e))

    return result