"""Bot administration routes with authentication, validation, and rate limiting."""
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Depends,
    HTTPException,
    Header,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator

from app.admin.bots import store

logger = logging.getLogger(__name__)

# Configuration
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_CONFIG_SIZE_BYTES = 1 * 1024 * 1024  # 1MB
RATE_LIMIT_REQUESTS = 100
RATE_LIMIT_WINDOW_SECONDS = 60

# In-memory rate limiting (for Lambda, consider external service for production)
_rate_limit_store: Dict[str, list[float]] = {}


# ============================================================================
# Pydantic Models for Request Validation
# ============================================================================


class NLUConfigRequest(BaseModel):
    """Request model for NLU configuration updates."""

    config: Dict[str, Any] = Field(..., description="NLU configuration object")

    @validator("config")
    def validate_config_not_empty(cls, v):
        """Ensure config is not empty."""
        if not v:
            raise ValueError("Configuration cannot be empty")
        return v

    class Config:
        """Pydantic config."""

        schema_extra = {
            "example": {
                "config": {
                    "intent_classifier": "sklearn",
                    "entity_extractor": "spacy",
                }
            }
        }


class BotImportResponse(BaseModel):
    """Response model for bot import operations."""

    num_intents_created: int = Field(..., description="Number of intents created")
    num_entities_created: int = Field(..., description="Number of entities created")
    message: str = Field(default="Import completed successfully")


class ConfigUpdateResponse(BaseModel):
    """Response model for config updates."""

    message: str = Field(default="Config updated successfully")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BotExportResponse(BaseModel):
    """Response model for bot export."""

    intents: list = Field(default_factory=list)
    entities: list = Field(default_factory=list)


# ============================================================================
# Authentication & Authorization
# ============================================================================


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Verify API key from request header.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        Verified API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    if not x_api_key:
        logger.warning("Request missing API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production, validate against a secure store (e.g., Secrets Manager)
    # For now, accept any non-empty key
    if len(x_api_key) < 8:
        logger.warning(f"Invalid API key format: {x_api_key[:4]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return x_api_key


# ============================================================================
# Rate Limiting
# ============================================================================


def check_rate_limit(client_id: str) -> None:
    """Check if client has exceeded rate limit.

    Args:
        client_id: Unique client identifier (e.g., API key hash)

    Raises:
        HTTPException: If rate limit exceeded
    """
    now = datetime.utcnow().timestamp()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    # Initialize or clean old entries
    if client_id not in _rate_limit_store:
        _rate_limit_store[client_id] = []

    # Remove old entries outside the window
    _rate_limit_store[client_id] = [
        ts for ts in _rate_limit_store[client_id] if ts > window_start
    ]

    # Check limit
    if len(_rate_limit_store[client_id]) >= RATE_LIMIT_REQUESTS:
        logger.warning(f"Rate limit exceeded for client: {client_id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS}s",
        )

    # Record this request
    _rate_limit_store[client_id].append(now)


# ============================================================================
# File Validation
# ============================================================================


async def validate_import_file(file: UploadFile) -> Dict[str, Any]:
    """Validate and parse import file.

    Args:
        file: Uploaded file

    Returns:
        Parsed JSON data

    Raises:
        HTTPException: If file is invalid
    """
    # Validate file type
    if file.content_type not in ["application/json", "text/plain"]:
        logger.warning(f"Invalid file type: {file.content_type}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file.content_type}. Expected application/json",
        )

    # Read file with size validation
    try:
        content = await file.read()

        if len(content) > MAX_FILE_SIZE_BYTES:
            logger.warning(
                f"File too large: {len(content)} bytes (max: {MAX_FILE_SIZE_BYTES})"
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large: {len(content)} bytes (max: {MAX_FILE_SIZE_BYTES} bytes)",
            )

        # Parse JSON
        json_data = json.loads(content)

        # Validate structure
        if not isinstance(json_data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Import file must contain a JSON object",
            )

        if "intents" not in json_data and "entities" not in json_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Import file must contain 'intents' or 'entities' keys",
            )

        return json_data

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in import file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading import file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing import file",
        )


# ============================================================================
# Routes
# ============================================================================

router = APIRouter(prefix="/bots", tags=["bots"])


@router.put("/{name}/config", response_model=ConfigUpdateResponse)
async def set_config(
    name: str,
    request: NLUConfigRequest,
    api_key: str = Depends(verify_api_key),
) -> ConfigUpdateResponse:
    """Update bot NLU configuration.

    Args:
        name: Bot name
        request: Configuration update request
        api_key: Verified API key

    Returns:
        ConfigUpdateResponse with update confirmation

    Raises:
        HTTPException: If bot not found or validation fails
    """
    # Rate limiting
    check_rate_limit(api_key)

    # Validate config size
    config_json = json.dumps(request.config)
    if len(config_json.encode()) > MAX_CONFIG_SIZE_BYTES:
        logger.warning(f"Config too large for bot {name}")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Configuration too large (max: {MAX_CONFIG_SIZE_BYTES} bytes)",
        )

    try:
        logger.info(f"Updating config for bot: {name}")
        await store.update_nlu_config(name, request.config)
        return ConfigUpdateResponse(
            message="Config updated successfully",
            updated_at=datetime.utcnow(),
        )
    except store.BotNotFoundError:
        logger.warning(f"Bot not found: {name}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot '{name}' not found",
        )
    except store.BotStoreError as e:
        logger.error(f"Store error updating config for {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration",
        )
    except Exception as e:
        logger.error(f"Unexpected error updating config for {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/{name}/config")
async def get_config(
    name: str,
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Get bot NLU configuration.

    Args:
        name: Bot name
        api_key: Verified API key

    Returns:
        NLU configuration dictionary

    Raises:
        HTTPException: If bot not found
    """
    # Rate limiting
    check_rate_limit(api_key)

    try:
        logger.info(f"Retrieving config for bot: {name}")
        config = await store.get_nlu_config(name)
        return config.model_dump() if hasattr(config, "model_dump") else config
    except store.BotNotFoundError:
        logger.warning(f"Bot not found: {name}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot '{name}' not found",
        )
    except store.BotStoreError as e:
        logger.error(f"Store error retrieving config for {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration",
        )
    except Exception as e:
        logger.error(f"Unexpected error retrieving config for {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/{name}/export")
async def export_bot(
    name: str,
    api_key: str = Depends(verify_api_key),
) -> Response:
    """Export all intents and entities for the bot as a JSON file.

    Args:
        name: Bot name
        api_key: Verified API key

    Returns:
        JSON file response with bot data

    Raises:
        HTTPException: If bot not found or export fails
    """
    # Rate limiting
    check_rate_limit(api_key)

    try:
        logger.info(f"Exporting bot: {name}")
        data = await store.export_bot(name)
        return Response(
            content=json.dumps(data),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment;filename=bot_{name}_export.json"
            },
        )
    except store.BotNotFoundError:
        logger.warning(f"Bot not found for export: {name}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot '{name}' not found",
        )
    except store.BotStoreError as e:
        logger.error(f"Store error exporting bot {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export bot",
        )
    except Exception as e:
        logger.error(f"Unexpected error exporting bot {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/{name}/import", response_model=BotImportResponse)
async def import_bot(
    name: str,
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key),
) -> BotImportResponse:
    """Import intents and entities from a JSON file for the bot.

    Supports async file processing for large imports. File size limited to 10MB.

    Args:
        name: Bot name
        file: JSON file with intents and entities
        api_key: Verified API key

    Returns:
        BotImportResponse with import statistics

    Raises:
        HTTPException: If file invalid, bot not found, or import fails
    """
    # Rate limiting
    check_rate_limit(api_key)

    try:
        logger.info(f"Starting import for bot: {name}")

        # Validate and parse file
        json_data = await validate_import_file(file)

        # Perform import
        result = await store.import_bot(name, json_data)

        logger.info(
            f"Import completed for bot {name}: "
            f"{result.get('num_intents_created', 0)} intents, "
            f"{result.get('num_entities_created', 0)} entities"
        )

        return BotImportResponse(
            num_intents_created=result.get("num_intents_created", 0),
            num_entities_created=result.get("num_entities_created", 0),
            message="Import completed successfully",
        )

    except store.BotNotFoundError:
        logger.warning(f"Bot not found for import: {name}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot '{name}' not found",
        )
    except store.BotStoreError as e:
        logger.error(f"Store error importing bot {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import bot data",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error importing bot {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during import",
        )


__all__ = ["router"]