import logging
import aiohttp
import asyncio
import time
from typing import Dict, Any, Optional, Callable
from aiohttp import ClientTimeout, TCPConnector
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger("http_client")


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class APICallException(Exception):
    """Exception raised for API call failures."""
    pass


class CircuitBreakerException(Exception):
    """Exception raised when circuit breaker is open."""
    pass


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff."""
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number with exponential backoff."""
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        if self.jitter:
            import random
            delay = delay * (0.5 + random.random())
        return delay


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""
    failure_threshold: int = 5
    recovery_timeout: int = 60
    success_threshold: int = 2


@dataclass
class HTTPMetrics:
    """Metrics collection for HTTP requests."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_retries: int = 0
    circuit_breaker_trips: int = 0
    total_response_time: float = 0.0
    
    def record_request(self, success: bool, response_time: float, retries: int = 0) -> None:
        """Record metrics for a request."""
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        self.total_retries += retries
        self.total_response_time += response_time
    
    def record_circuit_breaker_trip(self) -> None:
        """Record circuit breaker trip."""
        self.circuit_breaker_trips += 1
    
    def get_average_response_time(self) -> float:
        """Get average response time."""
        if self.total_requests == 0:
            return 0.0
        return self.total_response_time / self.total_requests
    
    def get_success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100


class CircuitBreaker:
    """Circuit breaker implementation for fault tolerance."""
    
    def __init__(self, config: CircuitBreakerConfig):
        """Initialize circuit breaker."""
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
    
    def record_success(self) -> None:
        """Record successful request."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker closed after successful recovery")
        elif self.state == CircuitBreakerState.CLOSED:
            self.failure_count = 0
    
    def record_failure(self) -> None:
        """Record failed request."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitBreakerState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                logger.warning(
                    f"Circuit breaker opened after {self.failure_count} failures"
                )
        elif self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
            self.success_count = 0
            logger.warning("Circuit breaker reopened during recovery")
    
    def can_execute(self) -> bool:
        """Check if request can be executed."""
        if self.state == CircuitBreakerState.CLOSED:
            return True
        
        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.config.recovery_timeout:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                    logger.info("Circuit breaker entering half-open state")
                    return True
            return False
        
        return self.state == CircuitBreakerState.HALF_OPEN


class HTTPClient:
    """HTTP client with retry logic, circuit breaker, connection pooling, and metrics."""
    
    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        pool_size: int = 10,
        timeout: int = 30,
    ):
        """
        Initialize HTTP client.
        
        Args:
            retry_config: Configuration for retry logic
            circuit_breaker_config: Configuration for circuit breaker
            pool_size: Connection pool size
            timeout: Default request timeout in seconds
        """
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker = CircuitBreaker(
            circuit_breaker_config or CircuitBreakerConfig()
        )
        self.pool_size = pool_size
        self.default_timeout = timeout
        self.metrics = HTTPMetrics()
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            connector = TCPConnector(
                limit=self.pool_size,
                limit_per_host=self.pool_size // 2,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session
    
    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    def _log_request(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        parameters: Optional[Dict[str, Any]],
    ) -> None:
        """Log request details."""
        logger.debug(
            f"HTTP Request: method={method} url={url} "
            f"headers={headers} parameters={parameters}"
        )
    
    def _log_response(
        self,
        url: str,
        status_code: int,
        response_time: float,
        response_size: int,
    ) -> None:
        """Log response details."""
        logger.debug(
            f"HTTP Response: url={url} status={status_code} "
            f"response_time={response_time:.2f}s response_size={response_size} bytes"
        )
    
    async def _execute_request(
        self,
        session: aiohttp.ClientSession,
        url: str,
        method: str,
        headers: Dict[str, str],
        parameters: Optional[Dict[str, Any]],
        is_json: bool,
        timeout_config: ClientTimeout,
    ) -> tuple[Dict[str, Any], int, float]:
        """Execute HTTP request and return response, status code, and response time."""
        start_time = time.time()
        method = method.upper()
        
        self._log_request(url, method, headers, parameters)
        
        try:
            if method == "GET":
                async with session.get(
                    url, headers=headers, params=parameters, timeout=timeout_config
                ) as response:
                    result = await response.json()
                    status_code = response.status
            elif method in ["POST", "PUT"]:
                kwargs = {
                    "headers": headers,
                    "timeout": timeout_config,
                    ("json" if is_json else "params"): parameters,
                }
                async with getattr(session, method.lower())(url, **kwargs) as response:
                    result = await response.json()
                    status_code = response.status
            elif method == "DELETE":
                async with session.delete(
                    url, headers=headers, params=parameters, timeout=timeout_config
                ) as response:
                    result = await response.json()
                    status_code = response.status
            else:
                raise ValueError(f"Unsupported request method: {method}")
            
            response_time = time.time() - start_time
            response_size = len(str(result).encode('utf-8'))
            
            self._log_response(url, status_code, response_time, response_size)
            
            if status_code >= 400:
                raise aiohttp.ClientError(
                    f"HTTP {status_code}: {result}"
                )
            
            return result, status_code, response_time
        
        except asyncio.TimeoutError as e:
            response_time = time.time() - start_time
            logger.error(f"Request timeout after {response_time:.2f}s: {url}")
            raise
        except aiohttp.ClientError as e:
            response_time = time.time() - start_time
            logger.error(f"HTTP error after {response_time:.2f}s: {str(e)}")
            raise
    
    async def call_api(
        self,
        url: str,
        method: str,
        headers: Optional[Dict[str, str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        is_json: bool = False,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Call external API with retry logic, circuit breaker, and metrics.
        
        Args:
            url: The API endpoint URL
            method: HTTP method (GET, POST, PUT, DELETE)
            headers: Optional request headers
            parameters: Optional request parameters or body
            is_json: Whether to send parameters as JSON body
            timeout: Request timeout in seconds (uses default if not specified)
        
        Returns:
            Dict containing the API response
        
        Raises:
            CircuitBreakerException: When circuit breaker is open
            APICallException: For HTTP-specific errors after retries exhausted
            asyncio.TimeoutError: When request times out
            ValueError: For invalid method types
        """
        if not self.circuit_breaker.can_execute():
            self.metrics.record_circuit_breaker_trip()
            raise CircuitBreakerException(
                f"Circuit breaker is {self.circuit_breaker.state.value}"
            )
        
        headers = headers or {}
        parameters = parameters or {}
        timeout_seconds = timeout or self.default_timeout
        timeout_config = ClientTimeout(total=timeout_seconds)
        
        session = await self._get_session()
        attempt = 0
        last_exception = None
        start_time = time.time()
        
        while attempt <= self.retry_config.max_retries:
            try:
                result, status_code, response_time = await self._execute_request(
                    session, url, method, headers, parameters, is_json, timeout_config
                )
                
                self.circuit_breaker.record_success()
                self.metrics.record_request(
                    success=True,
                    response_time=response_time,
                    retries=attempt,
                )
                logger.info(
                    f"API call successful: {method} {url} "
                    f"(attempt {attempt + 1}, {response_time:.2f}s)"
                )
                return result
            
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                attempt += 1
                
                if attempt <= self.retry_config.max_retries:
                    delay = self.retry_config.get_delay(attempt - 1)
                    logger.warning(
                        f"API call failed (attempt {attempt}): {str(e)}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    self.circuit_breaker.record_failure()
                    total_time = time.time() - start_time
                    self.metrics.record_request(
                        success=False,
                        response_time=total_time,
                        retries=attempt - 1,
                    )
                    logger.error(
                        f"API call failed after {attempt} attempts: {str(last_exception)}"
                    )
                    raise APICallException(
                        f"API call failed after {attempt} attempts: {str(last_exception)}"
                    )
        
        # Should not reach here
        raise APICallException("Unexpected error in retry logic")
    
    def get_metrics(self) -> HTTPMetrics:
        """Get collected metrics."""
        return self.metrics
    
    def reset_metrics(self) -> None:
        """Reset metrics."""
        self.metrics = HTTPMetrics()


# Convenience function for backward compatibility
async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Asynchronously call external API with improved error handling and timeout management.
    
    This is a convenience function that uses a default HTTPClient instance.
    For production use, consider creating an HTTPClient instance directly.
    
    Args:
        url: The API endpoint URL
        method: HTTP method (GET, POST, PUT, DELETE)
        headers: Optional request headers
        parameters: Optional request parameters or body
        is_json: Whether to send parameters as JSON body
        timeout: Request timeout in seconds
    
    Returns:
        Dict containing the API response
    
    Raises:
        APICallException: For HTTP-specific errors
        asyncio.TimeoutError: When request times out
        ValueError: For invalid method types
    """
    client = HTTPClient(timeout=timeout)
    try:
        return await client.call_api(
            url=url,
            method=method,
            headers=headers,
            parameters=parameters,
            is_json=is_json,
            timeout=timeout,
        )
    finally:
        await client.close()