import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Import types only for type-checking to avoid runtime circular imports
    from app.bot.dialogue_manager.dialogue_manager import DialogueManager  # noqa: F401

# Global holder for the shared DialogueManager used by route handlers.
_dialogue_manager: Optional["DialogueManager"] = None
# Lock to guard init/reload operations and avoid race conditions.
_init_lock = asyncio.Lock()


# Prometheus metrics (optional). If prometheus_client is unavailable we use no-op metrics.
class _NoopMetric:
    def observe(self, *_, **__):
        return None

    def inc(self, *_, **__):
        return None


try:
    from prometheus_client import Summary, Counter  # type: ignore

    DIALOGUE_MANAGER_RELOAD_DURATION = Summary(
        "dialogue_manager_reload_duration_seconds",
        "Duration in seconds for dialogue manager reloads",
    )
    DIALOGUE_MANAGER_RELOAD_FAILURES = Counter(
        "dialogue_manager_reload_failures_total",
        "Total number of dialogue manager reload failures",
    )
except Exception:
    DIALOGUE_MANAGER_RELOAD_DURATION = _NoopMetric()
    DIALOGUE_MANAGER_RELOAD_FAILURES = _NoopMetric()


async def get_dialogue_manager() -> Optional["DialogueManager"]:
    """Return the currently initialized DialogueManager or None.

    This function remains async to be usable as a FastAPI dependency.
    """
    global _dialogue_manager
    return _dialogue_manager


async def set_dialogue_manager(dialogue_manager: "DialogueManager") -> None:
    """Set the module-level DialogueManager instance.

    Provided for backwards compatibility and tests that patch the runtime object.
    """
    global _dialogue_manager
    _dialogue_manager = dialogue_manager


async def _resolve_dialogue_manager_factory(
    dialogue_manager_factory: Optional[Callable[..., Any]] = None,
) -> Callable[..., Any]:
    """Resolve a callable factory for creating a DialogueManager.

    The factory can be either a class exposing an async classmethod `from_config`
    or a callable returning either an instance or an awaitable.
    """
    if dialogue_manager_factory is not None:
        return dialogue_manager_factory

    # Lazy import to avoid circular imports at module import time.
    from app.bot.dialogue_manager.dialogue_manager import DialogueManager as _DM  # local import

    return _DM


async def init_dialogue_manager(
    dialogue_manager_factory: Optional[Callable[..., Any]] = None, **factory_kwargs: Any
) -> None:
    """Initialize the shared DialogueManager singleton in a race-free way.

    Parameters:
        dialogue_manager_factory: Optional factory (class or callable) used to create
            the DialogueManager instance. If omitted the default DialogueManager class
            is imported lazily.
        factory_kwargs: forwarded to the factory (e.g. injected dependencies for tests).
    """
    global _dialogue_manager

    async with _init_lock:
        if _dialogue_manager is not None:
            logger.debug("dialogue manager already initialized; skipping init")
            return

        factory = await _resolve_dialogue_manager_factory(dialogue_manager_factory)

        start = time.monotonic()
        try:
            # Support both async "from_config" classmethod and plain callable factories
            if hasattr(factory, "from_config"):
                maybe = factory.from_config(**factory_kwargs)
            else:
                maybe = factory(**factory_kwargs)

            dialogue_manager = await maybe if asyncio.iscoroutine(maybe) else maybe

            # Update model directory if provided by app_config (lazy import)
            try:
                from app.config import app_config as _app_config  # local import to avoid circularities

                models_dir = getattr(_app_config, "MODELS_DIR", None)
                if models_dir and hasattr(dialogue_manager, "update_model"):
                    dialogue_manager.update_model(models_dir)
            except Exception:
                # Non-fatal: model update is best-effort here
                logger.debug("could not update models_dir on init (may be missing configuration)")

            await set_dialogue_manager(dialogue_manager)

            duration = time.monotonic() - start
            try:
                DIALOGUE_MANAGER_RELOAD_DURATION.observe(duration)
            except Exception:
                # metric observation should not break startup
                logger.debug("failed to record reload duration metric")

            logger.info("dialogue manager initialized in %.3fs", duration)
        except Exception as exc:  # initialization failure
            DIALOGUE_MANAGER_RELOAD_FAILURES.inc()
            logger.exception("failed to initialize dialogue manager: %s", exc)
            raise


async def reload_dialogue_manager(
    dialogue_manager_factory: Optional[Callable[..., Any]] = None, **factory_kwargs: Any
) -> None:
    """Reload the DialogueManager instance safely and emit metrics for duration/failures.

    This will create a fresh instance via the provided factory (or default class) and
    replace the global instance atomically under the same lock used for initialization.
    """
    factory = await _resolve_dialogue_manager_factory(dialogue_manager_factory)

    async with _init_lock:
        start = time.monotonic()
        try:
            if hasattr(factory, "from_config"):
                maybe = factory.from_config(**factory_kwargs)
            else:
                maybe = factory(**factory_kwargs)

            dialogue_manager = await maybe if asyncio.iscoroutine(maybe) else maybe

            # Update models directory from config lazily
            try:
                from app.config import app_config as _app_config  # local import

                models_dir = getattr(_app_config, "MODELS_DIR", None)
                if models_dir and hasattr(dialogue_manager, "update_model"):
                    dialogue_manager.update_model(models_dir)
            except Exception:
                logger.debug("could not update models_dir on reload (may be missing configuration)")

            await set_dialogue_manager(dialogue_manager)

            duration = time.monotonic() - start
            try:
                DIALOGUE_MANAGER_RELOAD_DURATION.observe(duration)
            except Exception:
                logger.debug("failed to record reload duration metric")

            logger.info("dialogue manager reloaded in %.3fs", duration)
        except Exception as exc:
            DIALOGUE_MANAGER_RELOAD_FAILURES.inc()
            logger.exception("failed to reload dialogue manager: %s", exc)
            raise


@asynccontextmanager
async def dialogue_manager_lifespan(
    dialogue_manager_factory: Optional[Callable[..., Any]] = None, **factory_kwargs: Any
):
    """Async context manager for application lifespan that ensures the DialogueManager
    is initialized on enter and can be reloaded safely during runtime.

    Usage (FastAPI):
        async with dialogue_manager_lifespan():
            yield
    """
    await init_dialogue_manager(dialogue_manager_factory=dialogue_manager_factory, **factory_kwargs)
    try:
        yield
    finally:
        # Explicit teardown: clear the global reference so that next init starts fresh.
        global _dialogue_manager
        _dialogue_manager = None
        logger.info("dialogue manager torn down")