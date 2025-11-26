from typing import Any, Dict, Optional

from fastapi import APIRouter, UploadFile, File, Depends
from pydantic import BaseModel

from app.admin.bots.schemas import NLUConfiguration
from app.admin.bots.store import BotRepository, get_default_repository

router = APIRouter(prefix="/bots", tags=["bots"])


class MessageResponse(BaseModel):
    """Simple response carrying a human-readable message."""

    message: str


class ExportResponse(BaseModel):
    """DTO returned for export endpoints so adapters can control headers.

    `data` contains the exported payload. `filename` suggests a download
    filename if the transport supports Content-Disposition headers.
    """

    data: Dict[str, Any]
    filename: Optional[str] = "chatbot_data.json"


class ImportResult(BaseModel):
    """Summary of import results."""

    num_intents_created: int
    num_entities_created: int


class SetConfigRequest(BaseModel):
    """Request model for updating the bot NLU configuration."""

    nlu_config: NLUConfiguration


@router.put("/{name}/config", response_model=MessageResponse)
async def set_config(
    name: str,
    request: SetConfigRequest,
    repo: BotRepository = Depends(get_default_repository),
) -> MessageResponse:
    """Update bot config.

    This handler depends on an injected BotRepository so the same logic can
    be reused inside a Lambda adapter or a standalone FastAPI service.
    """
    # Persist the validated configuration as a plain dict to the repository
    await repo.update_nlu_config(name, request.nlu_config.model_dump())
    return MessageResponse(message="Config updated successfully")


@router.get("/{name}/config", response_model=NLUConfiguration)
async def get_config(name: str, repo: BotRepository = Depends(get_default_repository)) -> NLUConfiguration:
    """Get bot NLU configuration.

    Returns a NLUConfiguration model which can be serialized by FastAPI or a
    Lambda adapter.
    """
    return await repo.get_nlu_config(name)


@router.get("/{name}/export", response_model=ExportResponse)
async def export_bot(name: str, repo: BotRepository = Depends(get_default_repository)) -> ExportResponse:
    """Export all intents and entities for the bot as a JSON-compatible DTO.

    The returned ExportResponse contains the payload and a suggested filename.
    Transport-specific adapters are responsible for setting Content-Disposition
    headers when returning a file download to clients.
    """
    data = await repo.export_bot(name)
    return ExportResponse(data=data)


@router.post("/{name}/import", response_model=ImportResult)
async def import_bot(name: str, file: UploadFile = File(...), repo: BotRepository = Depends(get_default_repository)) -> ImportResult:
    """Import intents and entities from a JSON file for the bot.

    The endpoint accepts a multipart file upload when used with FastAPI. A
    Lambda adapter can instead pass the parsed JSON payload directly to the
    same repository-backed logic.
    """
    content = await file.read()
    json_data = __import__("json").loads(content)

    result = await repo.import_bot(name, json_data)
    return ImportResult(**result)