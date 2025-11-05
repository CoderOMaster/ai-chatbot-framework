from fastapi import APIRouter, Depends, HTTPException
from app.bot.dialogue_manager.models import UserMessage
from app.dependencies import get_dialogue_manager
from app.bot.dialogue_manager.dialogue_manager import (
    DialogueManager,
    DialogueManagerException,
)
from app.common.webhooks import parse_lambda_event_body
import os
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rest", tags=["rest"])


@router.post("/webbook")
async def webbook(
    body: dict, dialogue_manager: DialogueManager = Depends(get_dialogue_manager)
):
    """
    Endpoint to converse with the chatbot.
    Delegates the request processing to DialogueManager.

    :return: JSON response with the chatbot's reply and context.
    """

    user_message = UserMessage(
        thread_id=body["thread_id"], text=body["text"], context=body["context"]
    )
    try:
        new_state = await dialogue_manager.process(user_message)
    except DialogueManagerException as e:
        raise HTTPException(status_code=400, message=str(e))
    return new_state.bot_message


# Lambda-compatible handler
def handler(event: dict, context):
    """
    Minimal lambda handler that accepts a generic REST webhook, validates
    and optionally maps to canonical UserMessage format, then returns the
    payload to the caller or forwards based on environment.
    """
    try:
        body_bytes, headers = parse_lambda_event_body(event)
    except ValueError as e:
        logger.error("Failed to parse event body: %s", e)
        return {"statusCode": 400, "body": "Invalid request"}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        logger.exception("Invalid JSON payload")
        return {"statusCode": 400, "body": "Invalid JSON"}

    # map to canonical if present
    canonical = None
    if all(k in payload for k in ("thread_id", "text")):
        canonical = {"thread_id": payload.get("thread_id"), "text": payload.get("text"), "context": payload.get("context")}

    final_payload = canonical or payload

    # In this lightweight handler we simply return the canonical payload
    return {"statusCode": 200, "body": json.dumps(final_payload)}