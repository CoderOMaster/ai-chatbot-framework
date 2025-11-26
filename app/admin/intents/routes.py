from fastapi import APIRouter, HTTPException
from app.admin.intents import store
from app.admin.intents.schemas import Intent

router = APIRouter(prefix="/intents", tags=["intents"])


@router.post("/")
async def create_intent(intent: Intent):
    """Create a new intent"""
    intent_dict = intent.model_dump(exclude={"id"})
    intent = await store.add_intent(intent_dict)
    return intent


@router.get("/")
async def read_intents():
    """Get all intents"""
    intents, total_count = await store.list_intents()
    return {"intents": intents, "total": total_count}


@router.get("/{intent_id}")
async def read_intent(intent_id: str):
    """Get a specific intent by ID"""
    try:
        intent = await store.get_intent(intent_id)
        return intent
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{intent_id}")
async def update_intent(intent_id: str, intent: Intent):
    """Update an intent"""
    try:
        intent_dict = intent.model_dump(exclude={"id"})
        await store.edit_intent(intent_id, intent_dict)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{intent_id}")
async def delete_intent(intent_id: str):
    """Delete an intent"""
    try:
        await store.delete_intent(intent_id)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))