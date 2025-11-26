import httpx
from fastapi import APIRouter, HTTPException
from shared.models.dialogue import UserMessage
from shared.exceptions import DialogueManagerException

router = APIRouter(prefix="/test", tags=["test"])

# Dialogue manager service endpoint
DIALOGUE_MANAGER_SERVICE_URL = "http://dialogue-manager-service"


@router.post("/chat")
async def chat(body: dict):
    """
    Endpoint to converse with the chatbot.
    Delegates the request processing to DialogueManager service via HTTP.

    :return: JSON response with the chatbot's reply and context.
    """

    user_message = UserMessage(
        thread_id=body["thread_id"], text=body["text"], context=body["context"]
    )
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{DIALOGUE_MANAGER_SERVICE_URL}/process",
                json=user_message.dict(),
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DialogueManagerException as e:
        raise HTTPException(status_code=400, detail=str(e))