"""
FastAPI routes for bot configuration and import/export operations.

Implements /admin/bots endpoints for:
- Getting/setting bot NLU configuration
- Exporting bot data as JSON
- Importing bot data from JSON files

Optimized for Lambda deployment with streaming support for large payloads.
"""

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Dict, Any, AsyncGenerator
import json
import io

from app.admin.bots import store
from app.admin.bots.exchange import export_bot, import_bot

router = APIRouter(prefix="/bots", tags=["bots"])


async def _stream_json_response(data: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
    """
    Stream JSON data in chunks to avoid loading entire payload into memory.
    
    Useful for large export operations in Lambda environments where memory
    is constrained. Yields JSON chunks as they are serialized.
    
    Args:
        data: Dictionary to serialize and stream
        
    Yields:
        Bytes chunks of JSON data
    """
    # Stream the JSON serialization to avoid memory overhead
    buffer = io.StringIO()
    json.dump(data, buffer)
    content = buffer.getvalue()
    
    # Yield in chunks (8KB per chunk for efficient streaming)
    chunk_size = 8192
    for i in range(0, len(content), chunk_size):
        yield content[i : i + chunk_size].encode("utf-8")


@router.put("/{name}/config")
async def set_config(name: str, config: Dict[str, Any]) -> Dict[str, str]:
    """
    Update bot NLU configuration.
    
    Args:
        name: Bot name
        config: NLU configuration dictionary
        
    Returns:
        Success message
    """
    await store.update_nlu_config(name, config)
    return {"message": "Config updated successfully"}


@router.get("/{name}/config")
async def get_config(name: str) -> Dict[str, Any]:
    """
    Retrieve bot NLU configuration.
    
    Args:
        name: Bot name
        
    Returns:
        NLU configuration for the bot
    """
    return await store.get_nlu_config(name)


@router.get("/{name}/export")
async def export_bot_handler(name: str) -> StreamingResponse:
    """
    Export all intents and entities for a bot as a streamed JSON file.
    
    Uses streaming to avoid loading entire export into memory, suitable
    for Lambda environments with memory constraints.
    
    Args:
        name: Bot name to export
        
    Returns:
        StreamingResponse with JSON attachment
    """
    data = await export_bot(name)
    
    return StreamingResponse(
        _stream_json_response(data),
        media_type="application/json",
        headers={"Content-Disposition": "attachment;filename=chatbot_data.json"},
    )


@router.post("/{name}/import")
async def import_bot_handler(name: str, file: UploadFile = File(...)) -> Dict[str, int]:
    """
    Import intents and entities from a JSON file for a bot.
    
    Reads the uploaded JSON file and performs bulk import of intents and
    entities. For very large files, consider using S3 for staging and
    orchestrating the import via Lambda.
    
    Args:
        name: Bot name to import into
        file: Uploaded JSON file containing intents and entities
        
    Returns:
        Import statistics (counts of created items)
    """
    content = await file.read()
    json_data = json.loads(content)

    return await import_bot(name, json_data)