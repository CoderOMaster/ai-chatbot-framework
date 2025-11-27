"""Admin test endpoints for dialogue manager testing and validation.

This module provides endpoints for testing the dialogue manager service,
including message validation, test result caching, test history tracking,
and comparison with previous versions.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import hashlib
import json
import httpx

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test", tags=["test"])

# Configuration
DIALOGUE_MANAGER_SERVICE_URL = "http://dialogue-manager:8000"
CACHE_TTL_SECONDS = 3600
MAX_HISTORY_ENTRIES = 100


class MessageFormat(BaseModel):
    """Validated message format for testing."""
    
    thread_id: str = Field(..., min_length=1, description="Unique thread identifier")
    text: str = Field(..., min_length=1, max_length=5000, description="User message text")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional context")
    
    @validator("thread_id")
    def validate_thread_id(cls, v: str) -> str:
        """Validate thread_id format."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("thread_id must contain only alphanumeric characters, hyphens, and underscores")
        return v
    
    @validator("text")
    def validate_text(cls, v: str) -> str:
        """Validate text is not just whitespace."""
        if not v.strip():
            raise ValueError("text cannot be empty or whitespace only")
        return v.strip()


class TestResult(BaseModel):
    """Result of a single test message."""
    
    message_id: str
    thread_id: str
    input_text: str
    output: Dict[str, Any]
    timestamp: datetime
    cache_hit: bool = False
    version: str = "1.0"


class TestBatchResult(BaseModel):
    """Result of a batch test with multiple messages."""
    
    batch_id: str
    results: List[TestResult]
    total_messages: int
    successful: int
    failed: int
    timestamp: datetime
    duration_seconds: float


class TestHistory(BaseModel):
    """Historical test record for comparison."""
    
    batch_id: str
    timestamp: datetime
    version: str
    results_summary: Dict[str, Any]


# In-memory cache for test results (in production, use Redis)
_test_cache: Dict[str, tuple[TestResult, datetime]] = {}
_test_history: List[TestHistory] = []


def _generate_message_hash(message: MessageFormat) -> str:
    """Generate a hash for message caching.
    
    Args:
        message: The message to hash
        
    Returns:
        str: SHA256 hash of the message
    """
    content = f"{message.thread_id}:{message.text}:{json.dumps(message.context, sort_keys=True)}"
    return hashlib.sha256(content.encode()).hexdigest()


def _validate_auth_token(authorization: Optional[str] = Header(None)) -> str:
    """Validate authentication token.
    
    Args:
        authorization: Authorization header value
        
    Returns:
        str: Validated token
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = authorization.split(" ", 1)[1]
    if not token or len(token) < 10:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return token


def _get_cached_result(message_hash: str) -> Optional[TestResult]:
    """Get cached test result if available and not expired.
    
    Args:
        message_hash: Hash of the message
        
    Returns:
        Optional[TestResult]: Cached result if available and valid, None otherwise
    """
    if message_hash not in _test_cache:
        return None
    
    result, timestamp = _test_cache[message_hash]
    if datetime.utcnow() - timestamp > timedelta(seconds=CACHE_TTL_SECONDS):
        del _test_cache[message_hash]
        return None
    
    return result


def _cache_result(message_hash: str, result: TestResult) -> None:
    """Cache a test result.
    
    Args:
        message_hash: Hash of the message
        result: The test result to cache
    """
    _test_cache[message_hash] = (result, datetime.utcnow())


async def _call_dialogue_manager_service(message: MessageFormat) -> Dict[str, Any]:
    """Call the dialogue-manager service via HTTP.
    
    Args:
        message: The message to process
        
    Returns:
        Dict[str, Any]: Response from dialogue-manager service
        
    Raises:
        HTTPException: If service call fails
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{DIALOGUE_MANAGER_SERVICE_URL}/process",
                json=message.dict(),
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                logger.error(
                    f"Dialogue manager service error: {response.status_code} - {response.text}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Dialogue manager service error: {response.status_code}"
                )
            
            return response.json()
            
    except httpx.TimeoutException:
        logger.error("Dialogue manager service timeout")
        raise HTTPException(status_code=504, detail="Dialogue manager service timeout")
    except httpx.RequestError as e:
        logger.error(f"Dialogue manager service connection error: {e}")
        raise HTTPException(status_code=503, detail="Dialogue manager service unavailable")


@router.post("/chat")
async def chat(
    body: MessageFormat,
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Test endpoint to converse with the chatbot via dialogue-manager service.
    
    Validates message format, checks cache, and delegates to dialogue-manager service.
    Requires authentication via Bearer token.
    
    Args:
        body: The message to process (validated)
        authorization: Bearer token for authentication
        
    Returns:
        Dict[str, Any]: JSON response with the chatbot's reply and context
        
    Raises:
        HTTPException: If authentication fails, validation fails, or service error occurs
    """
    # Validate authentication
    _validate_auth_token(authorization)
    
    # Generate message hash for caching
    message_hash = _generate_message_hash(body)
    
    # Check cache
    cached_result = _get_cached_result(message_hash)
    if cached_result:
        logger.info(f"Cache hit for message: {message_hash}")
        cached_result.cache_hit = True
        return cached_result.dict()
    
    try:
        # Call dialogue-manager service
        output = await _call_dialogue_manager_service(body)
        
        # Create test result
        result = TestResult(
            message_id=message_hash,
            thread_id=body.thread_id,
            input_text=body.text,
            output=output,
            timestamp=datetime.utcnow(),
            cache_hit=False
        )
        
        # Cache the result
        _cache_result(message_hash, result)
        
        return result.dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/batch")
async def test_batch(
    messages: List[MessageFormat],
    authorization: Optional[str] = Header(None)
) -> TestBatchResult:
    """Test multiple messages asynchronously and return batch results.
    
    Processes multiple messages concurrently, caches results, and tracks history.
    Requires authentication via Bearer token.
    
    Args:
        messages: List of messages to process
        authorization: Bearer token for authentication
        
    Returns:
        TestBatchResult: Batch test results with summary statistics
        
    Raises:
        HTTPException: If authentication fails or batch processing fails
    """
    # Validate authentication
    _validate_auth_token(authorization)
    
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    if len(messages) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 messages per batch")
    
    batch_id = hashlib.sha256(
        f"{datetime.utcnow().isoformat()}".encode()
    ).hexdigest()[:16]
    
    start_time = datetime.utcnow()
    results: List[TestResult] = []
    successful = 0
    failed = 0
    
    # Process messages concurrently
    import asyncio
    
    async def process_message(msg: MessageFormat) -> Optional[TestResult]:
        """Process a single message with error handling."""
        try:
            message_hash = _generate_message_hash(msg)
            
            # Check cache
            cached_result = _get_cached_result(message_hash)
            if cached_result:
                cached_result.cache_hit = True
                return cached_result
            
            # Call service
            output = await _call_dialogue_manager_service(msg)
            
            result = TestResult(
                message_id=message_hash,
                thread_id=msg.thread_id,
                input_text=msg.text,
                output=output,
                timestamp=datetime.utcnow(),
                cache_hit=False
            )
            
            # Cache result
            _cache_result(message_hash, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing message in batch: {e}", exc_info=True)
            return None
    
    # Run all message processing concurrently
    batch_results = await asyncio.gather(
        *[process_message(msg) for msg in messages],
        return_exceptions=False
    )
    
    # Collect results
    for result in batch_results:
        if result:
            results.append(result)
            successful += 1
        else:
            failed += 1
    
    duration = (datetime.utcnow() - start_time).total_seconds()
    
    # Create batch result
    batch_result = TestBatchResult(
        batch_id=batch_id,
        results=results,
        total_messages=len(messages),
        successful=successful,
        failed=failed,
        timestamp=datetime.utcnow(),
        duration_seconds=duration
    )
    
    # Store in history
    history_entry = TestHistory(
        batch_id=batch_id,
        timestamp=datetime.utcnow(),
        version="1.0",
        results_summary={
            "total": len(messages),
            "successful": successful,
            "failed": failed,
            "cache_hits": sum(1 for r in results if r.cache_hit),
            "duration_seconds": duration
        }
    )
    
    _test_history.append(history_entry)
    if len(_test_history) > MAX_HISTORY_ENTRIES:
        _test_history.pop(0)
    
    logger.info(f"Batch test completed: {batch_id} - {successful}/{len(messages)} successful")
    
    return batch_result


@router.get("/history")
async def get_test_history(
    limit: int = Query(10, ge=1, le=100),
    authorization: Optional[str] = Header(None)
) -> List[TestHistory]:
    """Retrieve test history for comparison with previous versions.
    
    Args:
        limit: Maximum number of history entries to return
        authorization: Bearer token for authentication
        
    Returns:
        List[TestHistory]: Historical test records
        
    Raises:
        HTTPException: If authentication fails
    """
    # Validate authentication
    _validate_auth_token(authorization)
    
    return _test_history[-limit:]


@router.get("/compare")
async def compare_versions(
    batch_id_1: str = Query(..., description="First batch ID"),
    batch_id_2: str = Query(..., description="Second batch ID"),
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Compare test results between two batch versions.
    
    Args:
        batch_id_1: First batch ID for comparison
        batch_id_2: Second batch ID for comparison
        authorization: Bearer token for authentication
        
    Returns:
        Dict[str, Any]: Comparison results and differences
        
    Raises:
        HTTPException: If authentication fails or batches not found
    """
    # Validate authentication
    _validate_auth_token(authorization)
    
    # Find batches in history
    batch_1 = next((h for h in _test_history if h.batch_id == batch_id_1), None)
    batch_2 = next((h for h in _test_history if h.batch_id == batch_id_2), None)
    
    if not batch_1 or not batch_2:
        raise HTTPException(status_code=404, detail="One or both batch IDs not found")
    
    return {
        "batch_1": batch_1.dict(),
        "batch_2": batch_2.dict(),
        "differences": {
            "successful_delta": batch_2.results_summary["successful"] - batch_1.results_summary["successful"],
            "failed_delta": batch_2.results_summary["failed"] - batch_1.results_summary["failed"],
            "cache_hits_delta": batch_2.results_summary.get("cache_hits", 0) - batch_1.results_summary.get("cache_hits", 0),
            "duration_delta": batch_2.results_summary["duration_seconds"] - batch_1.results_summary["duration_seconds"]
        }
    }


@router.get("/cache-stats")
async def get_cache_stats(
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Get cache statistics for monitoring.
    
    Args:
        authorization: Bearer token for authentication
        
    Returns:
        Dict[str, Any]: Cache statistics
        
    Raises:
        HTTPException: If authentication fails
    """
    # Validate authentication
    _validate_auth_token(authorization)
    
    return {
        "cached_entries": len(_test_cache),
        "max_cache_size": 1000,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "history_entries": len(_test_history),
        "max_history_size": MAX_HISTORY_ENTRIES
    }