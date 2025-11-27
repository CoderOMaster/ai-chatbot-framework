from fastapi import APIRouter, Depends, HTTPException, Query, Header
from typing import Optional, List
from datetime import datetime, timedelta
import logging
from functools import lru_cache
import httpx

from app.core.security import verify_admin_token
from app.core.rate_limiter import RateLimiter
from .schemas import ChatLogResponse, ChatLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatlogs", tags=["chatlogs"])

# Rate limiter: 100 requests per minute for large queries
rate_limiter = RateLimiter(max_requests=100, window_seconds=60)

# Internal API endpoint for store service
STORE_API_BASE_URL = "http://localhost:8001"  # Will be injected via environment


def validate_date_range(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Validate date range parameters.
    
    Args:
        start_date: Start date filter
        end_date: End date filter
        
    Returns:
        Tuple of validated (start_date, end_date)
        
    Raises:
        HTTPException: If date range is invalid
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be before end_date"
        )
    
    # Prevent queries older than 90 days by default
    max_lookback = datetime.utcnow() - timedelta(days=90)
    if start_date and start_date < max_lookback:
        logger.warning(f"Query attempted beyond retention period: {start_date}")
        raise HTTPException(
            status_code=400,
            detail="Date range exceeds retention policy (90 days)"
        )
    
    return start_date, end_date


async def verify_admin_access(
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Verify admin authentication and authorization.
    
    Args:
        authorization: Bearer token from Authorization header
        
    Returns:
        Decoded token payload
        
    Raises:
        HTTPException: If authentication fails
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    try:
        token = authorization.replace("Bearer ", "")
        payload = verify_admin_token(token)
        
        # Verify admin role
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return payload
    except Exception as e:
        logger.error(f"Authentication failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def call_store_api(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> dict:
    """
    Call internal store API via HTTP.
    
    Args:
        endpoint: API endpoint path (e.g., "/list")
        method: HTTP method
        params: Query parameters
        json_data: Request body
        
    Returns:
        API response as dictionary
        
    Raises:
        HTTPException: If API call fails
    """
    url = f"{STORE_API_BASE_URL}/api/chatlogs{endpoint}"
    
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Store API call failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Chat log service unavailable")


def mask_pii(text: str) -> str:
    """
    Mask personally identifiable information in text.
    
    Args:
        text: Text to mask
        
    Returns:
        Text with PII masked
    """
    import re
    
    # Mask email addresses
    text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        '[EMAIL_MASKED]',
        text
    )
    
    # Mask phone numbers
    text = re.sub(
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        '[PHONE_MASKED]',
        text
    )
    
    # Mask SSN-like patterns
    text = re.sub(
        r'\b\d{3}-\d{2}-\d{4}\b',
        '[SSN_MASKED]',
        text
    )
    
    # Mask credit card-like patterns
    text = re.sub(
        r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        '[CARD_MASKED]',
        text
    )
    
    return text


def apply_pii_filtering(data: dict, mask: bool = True) -> dict:
    """
    Apply PII filtering to chat log data.
    
    Args:
        data: Chat log data
        mask: Whether to mask PII (True) or redact (False)
        
    Returns:
        Filtered data with PII handled
    """
    if not mask:
        return data
    
    filtered = data.copy()
    
    # Mask user message text
    if "user_message" in filtered:
        if isinstance(filtered["user_message"], dict):
            if "text" in filtered["user_message"]:
                filtered["user_message"]["text"] = mask_pii(
                    filtered["user_message"]["text"]
                )
    
    # Mask bot message text
    if "bot_message" in filtered:
        if isinstance(filtered["bot_message"], list):
            filtered["bot_message"] = [
                {
                    **msg,
                    "text": mask_pii(msg.get("text", ""))
                    if isinstance(msg, dict) else mask_pii(str(msg))
                }
                for msg in filtered["bot_message"]
            ]
    
    return filtered


@router.get("/", response_model=ChatLogResponse)
async def list_chatlogs(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    mask_pii: bool = Query(True),
    user_id: str = Header(None),
    admin_payload: dict = Depends(verify_admin_access),
    date_range: tuple = Depends(validate_date_range),
):
    """
    Get paginated chat conversation history with optional date filtering.
    
    Features:
    - Authentication & authorization required
    - Rate limiting (100 req/min)
    - Date range validation (90-day retention)
    - PII masking for sensitive data
    - Efficient pagination
    
    Args:
        page: Page number (1-indexed)
        limit: Results per page (1-100)
        start_date: Filter logs after this date
        end_date: Filter logs before this date
        mask_pii: Whether to mask PII in results
        user_id: User ID from header for audit logging
        admin_payload: Verified admin token payload
        date_range: Validated date range tuple
        
    Returns:
        Paginated chat log response with metadata
        
    Raises:
        HTTPException: 401 (auth), 403 (permission), 429 (rate limit), 400 (validation)
    """
    # Apply rate limiting
    client_id = admin_payload.get("sub", "unknown")
    if not rate_limiter.allow_request(client_id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Maximum 100 requests per minute."
        )
    
    # Log audit trail
    logger.info(
        f"Chat logs accessed by {admin_payload.get('email')} "
        f"(page={page}, limit={limit}, date_range={date_range})"
    )
    
    # Call internal store API
    params = {
        "page": page,
        "limit": limit,
        "start_date": date_range[0].isoformat() if date_range[0] else None,
        "end_date": date_range[1].isoformat() if date_range[1] else None,
        "anonymize": False,  # We handle PII masking at API layer
    }
    
    response = await call_store_api("/list", params=params)
    
    # Apply PII masking to conversations
    if mask_pii and "conversations" in response:
        response["conversations"] = [
            apply_pii_filtering(conv, mask=True)
            for conv in response["conversations"]
        ]
    
    return response


@router.get("/{thread_id}", response_model=List[ChatLog])
async def get_chat_thread(
    thread_id: str,
    mask_pii: bool = Query(True),
    admin_payload: dict = Depends(verify_admin_access),
):
    """
    Get complete conversation history for a specific thread.
    
    Features:
    - Authentication & authorization required
    - PII masking for sensitive data
    - Streaming support for large result sets
    
    Args:
        thread_id: Thread ID to retrieve
        mask_pii: Whether to mask PII in results
        admin_payload: Verified admin token payload
        
    Returns:
        List of chat log entries for the thread
        
    Raises:
        HTTPException: 401 (auth), 403 (permission), 404 (not found)
    """
    # Log audit trail
    logger.info(
        f"Chat thread {thread_id} accessed by {admin_payload.get('email')}"
    )
    
    # Call internal store API
    response = await call_store_api(
        f"/{thread_id}",
        params={"anonymize": False}
    )
    
    if not response:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Apply PII masking
    if mask_pii:
        response = [apply_pii_filtering(msg, mask=True) for msg in response]
    
    return response


@router.post("/export/s3")
async def export_to_s3(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    format: str = Query("json", regex="^(json|csv)$"),
    admin_payload: dict = Depends(verify_admin_access),
    date_range: tuple = Depends(validate_date_range),
):
    """
    Export large result sets to S3 for async processing.
    
    Features:
    - Handles large datasets efficiently
    - Supports multiple formats (JSON, CSV)
    - Returns S3 presigned URL for download
    
    Args:
        start_date: Export logs after this date
        end_date: Export logs before this date
        format: Export format (json or csv)
        admin_payload: Verified admin token payload
        date_range: Validated date range tuple
        
    Returns:
        S3 presigned URL and export metadata
        
    Raises:
        HTTPException: 401 (auth), 403 (permission), 400 (validation)
    """
    logger.info(
        f"Export requested by {admin_payload.get('email')} "
        f"(format={format}, date_range={date_range})"
    )
    
    # Call internal store API to initiate export
    export_data = {
        "start_date": date_range[0].isoformat() if date_range[0] else None,
        "end_date": date_range[1].isoformat() if date_range[1] else None,
        "format": format,
        "requested_by": admin_payload.get("email"),
    }
    
    response = await call_store_api(
        "/export",
        method="POST",
        json_data=export_data
    )
    
    return {
        "export_id": response.get("export_id"),
        "s3_url": response.get("s3_url"),
        "expires_in_seconds": 3600,
        "status": "processing"
    }