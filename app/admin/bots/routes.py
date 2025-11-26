"""
Bot admin routes for Lambda deployment.
Handles CRUD operations for bot configurations with input validation and streaming support.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Dict, Any, AsyncGenerator
import json
import logging

from app.admin.bots import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bots", tags=["bots"])

# Configuration constants
MAX_IMPORT_FILE_SIZE = 50 * 1024 * 1024  # 50MB limit for import files
MAX_CONFIG_SIZE = 1 * 1024 * 1024  # 1MB limit for config objects
CHUNK_SIZE = 8192  # 8KB chunks for streaming


class ValidationError(Exception):
    """Custom validation error for bot operations."""
    pass


def validate_bot_name(name: str) -> None:
    """
    Validate bot name format.
    
    Args:
        name: Bot name to validate
        
    Raises:
        ValidationError: If name is invalid
    """
    if not name or not isinstance(name, str):
        raise ValidationError("Bot name must be a non-empty string")
    if len(name) > 255:
        raise ValidationError("Bot name must be 255 characters or less")
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValidationError("Bot name must contain only alphanumeric characters, hyphens, and underscores")


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate bot configuration.
    
    Args:
        config: Configuration dictionary to validate
        
    Raises:
        ValidationError: If config is invalid
    """
    if not isinstance(config, dict):
        raise ValidationError("Config must be a dictionary")
    
    config_json = json.dumps(config)
    if len(config_json.encode('utf-8')) > MAX_CONFIG_SIZE:
        raise ValidationError(f"Config size exceeds {MAX_CONFIG_SIZE} bytes limit")


async def stream_export_data(name: str) -> AsyncGenerator[str, None]:
    """
    Stream bot export data in chunks to avoid loading entire file into memory.
    
    Args:
        name: Bot name to export
        
    Yields:
        JSON chunks as strings
    """
    try:
        data = await store.export_bot(name)
        
        # Stream JSON in chunks
        json_str = json.dumps(data)
        for i in range(0, len(json_str), CHUNK_SIZE):
            yield json_str[i:i + CHUNK_SIZE]
    except Exception as e:
        logger.error(f"Error streaming export for bot '{name}': {str(e)}")
        raise


@router.put("/{name}/config")
async def set_config(name: str, config: Dict[str, Any]):
    """
    Update bot configuration with validation.
    
    Args:
        name: Bot name
        config: Configuration dictionary
        
    Returns:
        Success message
        
    Raises:
        HTTPException: If validation fails or operation fails
    """
    try:
        validate_bot_name(name)
        validate_config(config)
        
        await store.update_nlu_config(name, config)
        return {"message": "Config updated successfully", "bot": name}
    except ValidationError as e:
        logger.warning(f"Validation error for bot '{name}': {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.warning(f"Bot not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating config for bot '{name}': {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update bot configuration")


@router.get("/{name}/config")
async def get_config(name: str):
    """
    Retrieve bot configuration.
    
    Args:
        name: Bot name
        
    Returns:
        NLU configuration
        
    Raises:
        HTTPException: If bot not found or operation fails
    """
    try:
        validate_bot_name(name)
        config = await store.get_nlu_config(name)
        return config
    except ValidationError as e:
        logger.warning(f"Validation error for bot '{name}': {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.warning(f"Bot not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving config for bot '{name}': {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bot configuration")


@router.get("/{name}/export")
async def export_bot(name: str):
    """
    Export bot configuration with streaming to handle large exports.
    
    Args:
        name: Bot name
        
    Returns:
        StreamingResponse with JSON data
        
    Raises:
        HTTPException: If bot not found or operation fails
    """
    try:
        validate_bot_name(name)
        
        return StreamingResponse(
            stream_export_data(name),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment;filename={name}_export.json"},
        )
    except ValidationError as e:
        logger.warning(f"Validation error for bot '{name}': {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.warning(f"Bot not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting bot '{name}': {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to export bot")


@router.post("/{name}/import")
async def import_bot(
    name: str,
    file: UploadFile = File(...),
    max_size: int = Query(MAX_IMPORT_FILE_SIZE, description="Maximum file size in bytes")
):
    """
    Import bot configuration from JSON file with size validation.
    
    Args:
        name: Bot name
        file: JSON file to import
        max_size: Maximum allowed file size
        
    Returns:
        Import summary with counts
        
    Raises:
        HTTPException: If validation fails or operation fails
    """
    try:
        validate_bot_name(name)
        
        # Read file with size limit
        content = b""
        async for chunk in file.file:
            content += chunk
            if len(content) > max_size:
                logger.warning(f"Import file for bot '{name}' exceeds size limit")
                raise ValidationError(f"File size exceeds {max_size} bytes limit")
        
        if not content:
            raise ValidationError("Import file is empty")
        
        # Parse JSON
        try:
            json_data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in import file for bot '{name}': {str(e)}")
            raise ValidationError(f"Invalid JSON format: {str(e)}")
        except UnicodeDecodeError:
            logger.warning(f"Invalid UTF-8 encoding in import file for bot '{name}'")
            raise ValidationError("File must be valid UTF-8 encoded JSON")
        
        result = await store.import_bot(name, json_data)
        return {
            "message": "Bot imported successfully",
            "bot": name,
            **result
        }
    except ValidationError as e:
        logger.warning(f"Validation error for bot '{name}': {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.warning(f"Invalid import data for bot '{name}': {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error importing bot '{name}': {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to import bot")