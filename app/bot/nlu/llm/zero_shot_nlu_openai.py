import logging
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from functools import wraps
from abc import ABC, abstractmethod

from app.bot.nlu.pipeline import NLUComponent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


class ResponseCache(ABC):
    """Abstract base class for response caching."""

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached response."""
        pass

    @abstractmethod
    def set(self, key: str, value: Dict[str, Any], ttl: int = 3600) -> None:
        """Store response in cache."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all cached responses."""
        pass


class InMemoryResponseCache(ResponseCache):
    """In-memory response cache with TTL support."""

    def __init__(self):
        """Initialize in-memory cache."""
        self._cache: Dict[str, tuple] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached response if not expired."""
        if key not in self._cache:
            return None
        
        value, expiry = self._cache[key]
        if datetime.now() > expiry:
            del self._cache[key]
            return None
        
        return value

    def set(self, key: str, value: Dict[str, Any], ttl: int = 3600) -> None:
        """Store response with TTL."""
        expiry = datetime.now() + timedelta(seconds=ttl)
        self._cache[key] = (value, expiry)

    def clear(self) -> None:
        """Clear all cached responses."""
        self._cache.clear()


class RedisResponseCache(ResponseCache):
    """Redis-based response cache for distributed caching."""

    def __init__(self, redis_client: Any, ttl: int = 3600):
        """Initialize Redis cache.
        
        Args:
            redis_client: Redis client instance
            ttl: Default time-to-live in seconds
        """
        self.redis_client = redis_client
        self.ttl = ttl
        self.prefix = "nlu_llm_cache:"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached response from Redis."""
        try:
            cached = self.redis_client.get(f"{self.prefix}{key}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis cache get error: {e}")
        return None

    def set(self, key: str, value: Dict[str, Any], ttl: int = None) -> None:
        """Store response in Redis with TTL."""
        try:
            ttl = ttl or self.ttl
            self.redis_client.setex(
                f"{self.prefix}{key}",
                ttl,
                json.dumps(value)
            )
        except Exception as e:
            logger.warning(f"Redis cache set error: {e}")

    def clear(self) -> None:
        """Clear all cached responses."""
        try:
            keys = self.redis_client.keys(f"{self.prefix}*")
            if keys:
                self.redis_client.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis cache clear error: {e}")


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        """Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: List[float] = []

    def is_allowed(self) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()
        cutoff = now - self.window_seconds
        
        self.requests = [req_time for req_time in self.requests if req_time > cutoff]
        
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        
        return False

    def wait_if_needed(self) -> float:
        """Wait until request is allowed, return wait time."""
        if self.is_allowed():
            return 0.0
        
        oldest_request = min(self.requests)
        wait_time = (oldest_request + self.window_seconds) - time.time()
        
        if wait_time > 0:
            time.sleep(wait_time)
        
        return max(0, wait_time)


class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
    ):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            expected_exception: Exception type to catch
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
            else:
                raise RuntimeError("Circuit breaker is open")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if recovery timeout has passed."""
        if self.last_failure_time is None:
            return False
        return time.time() - self.last_failure_time >= self.recovery_timeout

    def _on_success(self) -> None:
        """Handle successful call."""
        self.failure_count = 0
        self.state = "closed"

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
):
    """Decorator for retry logic with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for exponential backoff
        max_delay: Maximum delay between retries
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


class TokenUsageMonitor:
    """Monitor token usage and API costs."""

    def __init__(self, cost_per_1k_input: float = 0.0005, cost_per_1k_output: float = 0.0015):
        """Initialize token usage monitor.
        
        Args:
            cost_per_1k_input: Cost per 1000 input tokens
            cost_per_1k_output: Cost per 1000 output tokens
        """
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.request_count = 0

    def record_usage(self, input_tokens: int, output_tokens: int) -> float:
        """Record token usage and calculate cost.
        
        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Cost for this request
        """
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.request_count += 1
        
        cost = (input_tokens / 1000 * self.cost_per_1k_input +
                output_tokens / 1000 * self.cost_per_1k_output)
        self.total_cost += cost
        
        return cost

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics.
        
        Returns:
            Dictionary with usage stats
        """
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_requests": self.request_count,
            "total_cost": round(self.total_cost, 4),
            "avg_cost_per_request": round(self.total_cost / max(1, self.request_count), 6),
        }


class PromptVersionManager:
    """Manage prompt template versions."""

    def __init__(self, base_path: str = "app/bot/nlu/llm/prompts"):
        """Initialize prompt version manager.
        
        Args:
            base_path: Base path for prompt templates
        """
        self.base_path = base_path
        self.current_version = "1.0"
        self.templates: Dict[str, str] = {}

    def load_template(self, template_name: str, version: Optional[str] = None) -> str:
        """Load prompt template by name and version.
        
        Args:
            template_name: Name of the template
            version: Template version (uses current if not specified)
            
        Returns:
            Rendered template string
        """
        version = version or self.current_version
        env = Environment(loader=FileSystemLoader(self.base_path))
        
        versioned_name = f"{template_name.replace('.md', '')}_v{version}.md"
        
        try:
            template = env.get_template(versioned_name)
            return template.render()
        except Exception:
            logger.warning(f"Version {version} not found, falling back to {template_name}")
            template = env.get_template(template_name)
            return template.render()

    def set_version(self, version: str) -> None:
        """Set current prompt template version.
        
        Args:
            version: Version string (e.g., "1.0", "2.0")
        """
        self.current_version = version
        logger.info(f"Prompt template version set to {version}")


class FallbackNLUComponent:
    """Fallback NLU component for when LLM fails."""

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process message with fallback logic.
        
        Args:
            message: Input message
            
        Returns:
            Message with fallback results
        """
        message["intent"] = {"intent": None, "confidence": 0.0}
        message["intent_ranking"] = []
        message["entities"] = {}
        message["_fallback_used"] = True
        
        logger.info("Using fallback NLU component")
        return message


class ZeroShotNLUOpenAI(NLUComponent):
    """
    Zero-shot NLU component using OpenAI compatible language model API to extract intents and entities.
    
    Features:
    - Retry logic with exponential backoff
    - Rate limiting
    - Response caching
    - Fallback to traditional NLU
    - Token usage monitoring
    - Prompt versioning
    - Circuit breaker pattern
    """

    PROMPT_TEMPLATE_NAME = "ZERO_SHOT_LEARNING_PROMPT.md"

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        cache: Optional[ResponseCache] = None,
        enable_caching: bool = True,
        cache_ttl: int = 3600,
        max_requests_per_minute: int = 60,
        timeout_seconds: int = 30,
        use_fallback: bool = True,
        **kwargs,
    ):
        """Initialize ZeroShotNLUOpenAI component.
        
        Args:
            intents: List of intents to recognize
            entities: List of entities to extract
            cache: Custom cache implementation (uses InMemoryResponseCache if None)
            enable_caching: Whether to enable response caching
            cache_ttl: Cache time-to-live in seconds
            max_requests_per_minute: Rate limit for API requests
            timeout_seconds: Request timeout in seconds
            use_fallback: Whether to use fallback NLU on LLM failure
            **kwargs: Additional arguments for OpenAI configuration
        """
        super().__init__(name="ZeroShotNLUOpenAI", parallelizable=False)
        
        self.intents = intents or []
        self.entities = entities or []
        self.enable_caching = enable_caching
        self.cache_ttl = cache_ttl
        self.timeout_seconds = timeout_seconds
        self.use_fallback = use_fallback
        
        # Initialize cache
        self.cache = cache if cache is not None else InMemoryResponseCache()
        
        # Initialize rate limiter
        self.rate_limiter = RateLimiter(
            max_requests=max_requests_per_minute,
            window_seconds=60
        )
        
        # Initialize circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
        )
        
        # Initialize token usage monitor
        self.token_monitor = TokenUsageMonitor()
        
        # Initialize prompt version manager
        self.prompt_manager = PromptVersionManager()
        
        # Initialize fallback component
        self.fallback = FallbackNLUComponent()
        
        # Initialize the OpenAI LLM
        self.llm = ChatOpenAI(
            base_url=kwargs.get("base_url", "http://127.0.0.1:11434/v1"),
            api_key=kwargs.get("api_key", "not-need-for-local-models"),
            model_name=kwargs.get("model_name", "not-need-for-local-models"),
            temperature=kwargs.get("temperature", 0),
            request_timeout=timeout_seconds,
            extra_body={"max_tokens": kwargs.get("max_tokens", 4096)},
        )

        # Load and render the prompt template
        self._initialize_chain()
        
        self._is_loaded = True

    def _initialize_chain(self) -> None:
        """Initialize the LLM processing chain."""
        system_prompt = self.prompt_manager.load_template(self.PROMPT_TEMPLATE_NAME)
        
        # Render template with intents and entities
        env = Environment(loader=FileSystemLoader("app/bot/nlu/llm/prompts"))
        template = env.get_template(self.PROMPT_TEMPLATE_NAME)
        system_prompt = template.render(
            {"intents": self.intents, "entities": self.entities}
        )

        # Define the prompt template
        prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{text}"),
            ]
        )

        # Define the processing chain
        self.chain = prompt_template | self.llm | JsonOutputParser()

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text.
        
        Args:
            text: Input text
            
        Returns:
            Cache key hash
        """
        key_data = f"{text}:{','.join(sorted(self.intents))}:{','.join(sorted(self.entities))}"
        return hashlib.md5(key_data.encode()).hexdigest()

    @retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
    def _call_llm(self, text: str) -> Dict[str, Any]:
        """Call LLM with retry logic.
        
        Args:
            text: Input text to process
            
        Returns:
            LLM response
            
        Raises:
            Exception: If all retries fail
        """
        self.rate_limiter.wait_if_needed()
        
        def _invoke():
            return self.chain.invoke({"text": text})
        
        return self.circuit_breaker.call(_invoke)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Placeholder for training functionality. Not implemented for zero-shot learning.
        
        Args:
            training_data: Training data (unused)
            model_path: Model path (unused)
        """
        logger.info("Zero-shot learning does not require training")

    def load(self, model_path: str) -> bool:
        """Load component. For zero-shot learning, initialization is sufficient.
        
        Args:
            model_path: Model path (unused)
            
        Returns:
            True if load successful
        """
        self._is_loaded = True
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and extract intents and entities using the OpenAI model.

        Args:
            message: Input message containing the text to process

        Returns:
            Processed message with extracted intents and entities
        """
        if not message.get("text"):
            logger.warning("Message does not contain 'text' key. Skipping processing.")
            return message

        text = message.get("text")
        cache_key = self._get_cache_key(text) if self.enable_caching else None

        # Try to get from cache
        if cache_key:
            cached_result = self.cache.get(cache_key)
            if cached_result:
                logger.debug(f"Cache hit for text: {text[:50]}...")
                message.update(cached_result)
                return message

        try:
            # Call LLM with retry and rate limiting
            result = self._call_llm(text)

            # Extract intent
            intent_value = result.get("intent")
            if intent_value:
                intent = {
                    "intent": intent_value,
                    "confidence": 1.0,
                }
                message["intent"] = intent
                message["intent_ranking"] = [intent]
            else:
                message["intent"] = {"intent": None, "confidence": 0.0}

            # Extract and filter entities
            entities = result.get("entities", {})
            message["entities"] = {k: v for k, v in entities.items() if v is not None}

            # Cache the result
            if cache_key:
                cache_data = {
                    "intent": message.get("intent"),
                    "intent_ranking": message.get("intent_ranking", []),
                    "entities": message.get("entities", {}),
                }
                self.cache.set(cache_key, cache_data, self.cache_ttl)

            # Record token usage (estimate)
            self.token_monitor.record_usage(
                input_tokens=len(text.split()) * 2,
                output_tokens=50
            )

        except Exception as e:
            logger.error(f"Error processing message with LLM: {e}", exc_info=True)
            
            if self.use_fallback:
                logger.info("Falling back to default NLU response")
                message = self.fallback.process(message)
            else:
                message["intent"] = {"intent": None, "confidence": 0.0}
                message["intent_ranking"] = []
                message["entities"] = {}

        return message

    def get_token_stats(self) -> Dict[str, Any]:
        """Get token usage statistics.
        
        Returns:
            Dictionary with token usage stats
        """
        return self.token_monitor.get_stats()

    def clear_cache(self) -> None:
        """Clear response cache."""
        self.cache.clear()
        logger.info("Response cache cleared")

    def set_prompt_version(self, version: str) -> None:
        """Set prompt template version.
        
        Args:
            version: Version string (e.g., "1.0", "2.0")
        """
        self.prompt_manager.set_version(version)
        self._initialize_chain()
        logger.info(f"Prompt version updated to {version}")

    def get_circuit_breaker_status(self) -> str:
        """Get circuit breaker status.
        
        Returns:
            Circuit breaker state (closed, open, half-open)
        """
        return self.circuit_breaker.state