import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional, Callable
from aiohttp import ClientTimeout
from enum import Enum
from datetime import datetime, timedelta
from dataclasses import dataclass, field


logger = logging.getLogger("http_client")


class LogVerbosity(Enum):
    """Configurable logging verbosity levels."""
    SILENT = 0
    ERROR_ONLY = 1
    STANDARD = 2
    VERBOSE = 3


class APICallException(Exception):
    """Base exception for API call failures."""
    pass


class CircuitBreakerOpenException(APICallException):
    """Raised when circuit breaker is in OPEN state."""
    pass


class RetryExhausted(APICallException):
    """Raised when all retry attempts are exhausted."""
    pass


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff."""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_status_codes: set = field(default_factory=lambda: {408, 429, 500, 502, 503, 504})

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number with exponential backoff."""
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        if self.jitter:
            import random
            delay *= random.uniform(0.8, 1.2)
        return delay


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2


class CircuitBreaker:
    """Circuit breaker implementation to prevent cascading failures."""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None

    def record_success(self) -> None:
        """Record a successful call."""
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
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

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

    def can_attempt(self) -> bool:
        """Check if a call attempt should be allowed."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time:
                elapsed = datetime.utcnow() - self.last_failure_time
                if elapsed >= timedelta(seconds=self.config.recovery_timeout):
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                    logger.info("Circuit breaker entering half-open state for recovery")
                    return True
            return False

        return self.state == CircuitBreakerState.HALF_OPEN

    def get_state(self) -> str:
        """Get current circuit breaker state."""
        return self.state.value


@dataclass
class HTTPClientConfig:
    """Configuration for HTTP client."""
    timeout: int = 30
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    log_verbosity: LogVerbosity = LogVerbosity.STANDARD
    enable_circuit_breaker: bool = True


class HTTPClient:
    """Async HTTP client with retry logic, circuit breaker, and enhanced error handling."""

    def __init__(self, config: Optional[HTTPClientConfig] = None):
        self.config = config or HTTPClientConfig()
        self.circuit_breaker = CircuitBreaker(self.config.circuit_breaker_config)
        self._log = self._create_logger()

    def _create_logger(self) -> Callable:
        """Create a logger function based on verbosity level."""
        def log_func(level: str, message: str) -> None:
            if self.config.log_verbosity == LogVerbosity.SILENT:
                return
            if level == "error" or self.config.log_verbosity.value >= LogVerbosity.STANDARD.value:
                getattr(logger, level)(message)
            elif level == "debug" and self.config.log_verbosity == LogVerbosity.VERBOSE:
                logger.debug(message)

        return log_func

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
        Asynchronously call external API with retry logic and circuit breaker.

        Args:
            url: The API endpoint URL
            method: HTTP method (GET, POST, PUT, DELETE)
            headers: Optional request headers
            parameters: Optional request parameters or body
            is_json: Whether to send parameters as JSON body
            timeout: Request timeout in seconds (uses config default if not specified)

        Returns:
            Dict containing the API response

        Raises:
            CircuitBreakerOpenException: When circuit breaker is open
            RetryExhausted: When all retry attempts are exhausted
            APICallException: For other API call failures
        """
        timeout = timeout or self.config.timeout

        if self.config.enable_circuit_breaker and not self.circuit_breaker.can_attempt():
            self._log("error", f"Circuit breaker is {self.circuit_breaker.get_state()}")
            raise CircuitBreakerOpenException(
                f"Circuit breaker is {self.circuit_breaker.get_state()}"
            )

        last_exception: Optional[Exception] = None

        for attempt in range(self.config.retry_config.max_attempts):
            try:
                result = await self._execute_request(
                    url, method, headers, parameters, is_json, timeout
                )
                if self.config.enable_circuit_breaker:
                    self.circuit_breaker.record_success()
                return result

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                if self.config.enable_circuit_breaker:
                    self.circuit_breaker.record_failure()

                is_retryable = self._is_retryable_error(e)
                if not is_retryable or attempt == self.config.retry_config.max_attempts - 1:
                    self._log("error", f"API call failed (attempt {attempt + 1}): {str(e)}")
                    break

                delay = self.config.retry_config.get_delay(attempt)
                self._log(
                    "debug",
                    f"Retrying after {delay:.2f}s (attempt {attempt + 1}/{self.config.retry_config.max_attempts})"
                )
                await asyncio.sleep(delay)

            except Exception as e:
                last_exception = e
                if self.config.enable_circuit_breaker:
                    self.circuit_breaker.record_failure()
                self._log("error", f"Unexpected error during API call: {str(e)}")
                break

        raise RetryExhausted(
            f"API call exhausted after {self.config.retry_config.max_attempts} attempts: {str(last_exception)}"
        )

    async def _execute_request(
        self,
        url: str,
        method: str,
        headers: Optional[Dict[str, str]],
        parameters: Optional[Dict[str, Any]],
        is_json: bool,
        timeout: int,
    ) -> Dict[str, Any]:
        """Execute a single HTTP request."""
        headers = headers or {}
        parameters = parameters or {}
        timeout_config = ClientTimeout(total=timeout)
        method = method.upper()

        self._log(
            "debug",
            f"HTTP {method} request: url={url}, headers={headers}, params={parameters}"
        )

        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            if method == "GET":
                async with session.get(url, headers=headers, params=parameters) as response:
                    return await self._handle_response(response, url, method)

            elif method in ["POST", "PUT"]:
                kwargs = {
                    "headers": headers,
                    ("json" if is_json else "params"): parameters,
                }
                async with getattr(session, method.lower())(url, **kwargs) as response:
                    return await self._handle_response(response, url, method)

            elif method == "DELETE":
                async with session.delete(url, headers=headers, params=parameters) as response:
                    return await self._handle_response(response, url, method)

            else:
                raise ValueError(f"Unsupported request method: {method}")

    async def _handle_response(
        self, response: aiohttp.ClientResponse, url: str, method: str
    ) -> Dict[str, Any]:
        """Handle HTTP response and raise appropriate exceptions."""
        try:
            result = await response.json()
        except Exception as e:
            self._log("error", f"Failed to parse JSON response from {url}: {str(e)}")
            raise APICallException(f"Failed to parse JSON response: {str(e)}")

        self._log("debug", f"HTTP {method} {url} => Status: {response.status}, Response: {result}")

        if response.status >= 400:
            error_msg = f"HTTP {response.status} error for {method} {url}: {result}"
            self._log("error", error_msg)
            raise aiohttp.ClientError(error_msg)

        return result

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error is retryable."""
        if isinstance(error, asyncio.TimeoutError):
            return True
        if isinstance(error, aiohttp.ClientError):
            return True
        return False


# Backwards compatibility: standalone function
async def call_api(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    is_json: bool = False,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Asynchronously call external API (backwards compatible wrapper).

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
        APICallException: For API call failures
    """
    client = HTTPClient(HTTPClientConfig(timeout=timeout))
    return await client.call_api(url, method, headers, parameters, is_json, timeout)