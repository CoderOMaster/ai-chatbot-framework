from typing import Any, Dict

import anyio
import json
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response

from app.admin.bots import schemas

router = APIRouter(prefix="/bots", tags=["bots"]) 

# Configurable max upload size (bytes) for bot imports
MAX_IMPORT_SIZE = 5 * 1024 * 1024  # 5 MB


class OperationResult(BaseModel):
    """Simple operation result payload."""

    message: str


class ImportQueuedResult(OperationResult):
    """Result returned when an import has been scheduled."""

    queued: bool = True


def get_bots_store() -> Any:
    """Dependency returning the bots store module.

    This indirection allows tests to override the dependency with a fake
    implementation. The store exposes async functions: update_nlu_config,
    get_nlu_config, export_bot and import_bot.
    """
    from app.admin.bots import store as _store

    return _store


@router.put("/{name}/config", response_model=OperationResult)
async def set_config(name: str, config: Dict[str, Any], store: Any = Depends(get_bots_store)) -> OperationResult:
    """Update bot NLU configuration.

    The incoming payload is validated at the router level (as a plain dict)
    and passed to the store which is responsible for persistence.
    """
    await store.update_nlu_config(name, config)
    return OperationResult(message="Config updated successfully")


@router.get("/{name}/config", response_model=schemas.NLUConfiguration)
async def get_config(name: str, store: Any = Depends(get_bots_store)) -> schemas.NLUConfiguration:
    """Return the bot's NLU configuration.

    Returns 404-like empty response (None) when the bot does not exist to
    mirror previous behaviour. Consumers should handle missing values.
    """
    config = await store.get_nlu_config(name)
    if config is None:
        # Keep previous behaviour: return None (FastAPI will render as null)
        return None  # type: ignore[return-value]
    # Normalize to Pydantic model for consistent response
    return schemas.NLUConfiguration.model_validate(config)


@router.get("/{name}/export")
async def export_bot(name: str, store: Any = Depends(get_bots_store)) -> Response:
    """Export bot data as a JSON attachment."""
    data = await store.export_bot(name)
    content = json.dumps(data)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment;filename={name}_chatbot_data.json"},
    )


async def _background_import(name: str, file_bytes: bytes, store: Any) -> None:
    """Background task which parses and imports bot data.

    CPU-bound JSON parsing is offloaded to a thread to avoid blocking the
    event loop. The store.import_bot function is async and is awaited.
    """
    # Parse JSON in a thread to avoid blocking the event loop
    try:
        text = file_bytes.decode("utf-8")
    except Exception:
        # if decoding fails, skip import
        return

    try:
        data = await anyio.to_thread.run_sync(json.loads, text)
    except Exception:
        # Silently ignore invalid payloads in background import
        return

    try:
        await store.import_bot(name, data)
    except Exception:
        # Swallow exceptions to avoid crashing background worker; logging can be
        # added later via injected logger dependency if required.
        return


@router.post("/{name}/import", response_model=ImportQueuedResult)
async def import_bot(name: str, background_tasks: BackgroundTasks, file: UploadFile = File(...), store: Any = Depends(get_bots_store)) -> ImportQueuedResult:
    """Schedule an import of intents and entities from an uploaded JSON file.

    The uploaded file is read up to MAX_IMPORT_SIZE + 1 bytes; if it exceeds
    the configured limit a 413 error is returned. The actual JSON parsing and
    database import runs in a background task to avoid blocking the request
    cycle.
    """
    # Read at most MAX_IMPORT_SIZE + 1 to detect oversized uploads
    content = await file.read(MAX_IMPORT_SIZE + 1)
    if len(content) > MAX_IMPORT_SIZE:
        raise HTTPException(status_code=413, detail="Uploaded file too large")

    # Schedule heavy work in the background
    background_tasks.add_task(_background_import, name, content, store)

    return ImportQueuedResult(message="Import scheduled", queued=True)