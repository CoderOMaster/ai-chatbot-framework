import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from jinja2 import Template

from app.bot.dialogue_manager.utils import SilentUndefined, split_sentence
from app.bot.dialogue_manager.models import IntentModel, ParameterModel, UserMessage
from app.bot.memory import MemorySaver
from app.bot.memory.models import State

logger = logging.getLogger("dialogue_manager")


class DialogueManagerException(Exception):
    """General DialogueManager error."""


class Observability:
    """Lightweight observability helpers for tracing phases and counting occurrences.

    This is intentionally simple so callers can swap it with a more
    feature-rich implementation (Prometheus, OpenTelemetry) later.
    """

    def __init__(self) -> None:
        self.counters: Dict[str, int] = defaultdict(int)

    def incr(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount
        logger.debug("obs.counter %s=%s", name, self.counters[name])

    def trace(self, phase: str):
        """Context manager to time a phase.

        Usage:
            with obs.trace("nlu.process"):
                ...
        """

        start = time.perf_counter()

        class _TraceCtx:
            def __enter__(self_inner):
                return None

            def __exit__(self_inner, exc_type, exc, tb):
                duration = time.perf_counter() - start
                logger.debug("obs.trace %s took %.4fs", phase, duration)
                self.incr(f"phase.{phase}.calls")
                # Optionally store durations, histograms, etc.

        return _TraceCtx()


class BotConfigService:
    """Service that fetches and caches bot configuration with a TTL.

    The underlying get_bot function is imported lazily to allow injection
    during testing or swapping persistence layers.
    """

    def __init__(self, get_bot_func: Optional[Callable[[str], Any]] = None, ttl_secs: int = 300) -> None:
        self._get_bot_func = get_bot_func
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl_secs
        self._lock = asyncio.Lock()

    async def get(self, bot_id: str = "default") -> Any:
        """Return bot configuration, using cache when valid."""
        now = time.time()
        cached = self._cache.get(bot_id)
        if cached and now - cached[0] < self._ttl:
            return cached[1]

        async with self._lock:
            # Double-check after acquiring lock
            cached = self._cache.get(bot_id)
            if cached and now - cached[0] < self._ttl:
                return cached[1]

            if self._get_bot_func is None:
                # import lazily to avoid tight coupling at module import
                from app.admin.bots.store import get_bot as _default_get_bot

                self._get_bot_func = _default_get_bot

            bot = await self._get_bot_func(bot_id)
            self._cache[bot_id] = (time.time(), bot)
            return bot


class NLUService:
    """NLU pipeline manager that loads pipelines lazily per bot and caches them
    with an LRU/TTL strategy.
    """

    def __init__(self, get_pipeline_func: Optional[Callable[[], Any]] = None, ttl_secs: int = 600) -> None:
        self._get_pipeline_func = get_pipeline_func
        self._pipelines: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl_secs
        self._lock = asyncio.Lock()

    async def get_pipeline(self, bot_id: str = "default") -> Optional[Any]:
        """Return an initialized NLU pipeline for the bot or None if models missing."""
        now = time.time()
        cached = self._pipelines.get(bot_id)
        if cached and now - cached[0] < self._ttl:
            return cached[1]

        async with self._lock:
            cached = self._pipelines.get(bot_id)
            if cached and now - cached[0] < self._ttl:
                return cached[1]

            if self._get_pipeline_func is None:
                from app.bot.nlu.pipeline_utils import get_pipeline as _default_get_pipeline

                self._get_pipeline_func = _default_get_pipeline

            try:
                pipeline = await self._get_pipeline_func()
            except Exception as e:  # models missing or loading error
                logger.warning("NLU pipeline load failed for bot %s: %s", bot_id, e)
                pipeline = None

            self._pipelines[bot_id] = (time.time(), pipeline)
            return pipeline


class SlotFillingService:
    """Handles parameter extraction and missing-parameter prompts."""

    def __init__(self) -> None:
        pass

    def process_intent(self, query_intent: IntentModel, active_intent: IntentModel, current_state: State) -> Tuple[State, IntentModel]:
        """Populate extracted parameters from NLU entities and determine missing prompts.

        This function preserves earlier behavior but is encapsulated to make testing
        and extension easier.
        """
        # cancel intent should cancel active intent and reset chat model
        if query_intent.intent_id == "cancel":
            active_intent = query_intent
            current_state.complete = True
            current_state.parameters = []
            current_state.extracted_parameters = {}
            current_state.missing_parameters = []
            current_state.current_node = None
            return current_state, active_intent

        parameters = active_intent.parameters

        if parameters:
            # Get entities from NLU pipeline result
            extracted_entities = current_state.nlu.get("entities", {})

            # Group entities by type
            entities_by_type: Dict[str, List[Any]] = {}
            for entity_name, entity_value in extracted_entities.items():
                entities_by_type.setdefault(entity_name, []).append(entity_value)

            # populate parameters structure if empty
            if len(current_state.parameters) == 0:
                for param in parameters:
                    current_state.parameters.append(
                        {"name": param.name, "type": param.type, "required": param.required}
                    )

            # Match extracted entities with parameters based on type
            for param in parameters:
                # For free_text parameters being prompted
                if param.type == "free_text" and current_state.current_node == param.name:
                    current_state.extracted_parameters[param.name] = current_state.user_message.text
                    continue

                # Get all entities of matching type
                avail = entities_by_type.get(param.type)
                if avail:
                    current_state.extracted_parameters[param.name] = avail.pop(0)

            # Handle missing parameters
            current_state = self._handle_missing_parameters(parameters, current_state)

        # Check if there are no missing parameters to mark the intent as complete
        current_state.complete = not bool(current_state.missing_parameters)
        return current_state, active_intent

    def _handle_missing_parameters(self, parameters: List[ParameterModel], current_state: State) -> State:
        """Internal helper to identify and prompt for missing parameters."""
        missing_parameters: List[ParameterModel] = []
        current_state.missing_parameters = []

        # clear current node and bot messages
        current_state.current_node = None
        current_state.bot_message = []

        for parameter in parameters:
            if parameter.required and parameter.name not in current_state.extracted_parameters:
                current_state.missing_parameters.append(parameter.name)
                missing_parameters.append(parameter)

        if missing_parameters:
            current_node = missing_parameters[0]
            current_state.current_node = current_node.name
            current_state.bot_message = [{"text": msg} for msg in split_sentence(current_node.prompt)]
        return current_state


class APIService:
    """Handles API triggers for intents, wrapping lower-level http client calls.

    Ensures request-id propagation and consistent template rendering with
    SilentUndefined.
    """

    def __init__(self, call_api_func: Optional[Callable[..., Any]] = None) -> None:
        self._call_api_func = call_api_func

    async def call_intent_api(self, intent: IntentModel, current_state: State, request_id: Optional[str] = None) -> Any:
        api_details = intent.api_details
        headers = api_details.get_headers() or {}
        if request_id:
            headers.setdefault("X-Request-ID", request_id)

        url_template = Template(api_details.url, undefined=SilentUndefined)
        rendered_url = url_template.render(context=current_state.context, parameters=current_state.extracted_parameters)

        if api_details.is_json:
            request_template = Template(api_details.json_data, undefined=SilentUndefined)
            request_json = request_template.render(context=current_state.context, parameters=current_state.extracted_parameters)
            parameters = json.loads(request_json)
        else:
            parameters = current_state.extracted_parameters

        if self._call_api_func is None:
            from app.bot.dialogue_manager.http_client import call_api as _default_call_api

            self._call_api_func = _default_call_api

        try:
            return await self._call_api_func(rendered_url, api_details.request_type, headers, parameters, api_details.is_json)
        except Exception as e:
            # Surface more granular messages while avoiding tight coupling to http client types
            log_extra = {"intent": getattr(intent, "intent_id", None), "thread_id": getattr(current_state, "thread_id", None)}
            logger.warning("API call failed: %s, extra=%s", e, log_extra)
            # If the underlying exception has attributes like status_code or timeout, include them
            if hasattr(e, "status_code"):
                raise DialogueManagerException(f"API call failed with status {getattr(e, 'status_code')}")
            if getattr(e, "args", None):
                raise DialogueManagerException(str(e))
            raise DialogueManagerException("API call failed")


class DialogueManager:
    """Orchestrates NLU, slot-filling and API calling to process user messages.

    Dependencies are injected to keep this class testable and free of legacy globals.
    """

    def __init__(
        self,
        memory_saver: MemorySaver,
        intents: List[IntentModel],
        nlu_service: Optional[NLUService] = None,
        slot_service: Optional[SlotFillingService] = None,
        api_service: Optional[APIService] = None,
        bot_config_service: Optional[BotConfigService] = None,
        observability: Optional[Observability] = None,
    ) -> None:
        self.memory_saver = memory_saver
        self.nlu_service = nlu_service or NLUService()
        self.slot_service = slot_service or SlotFillingService()
        self.api_service = api_service or APIService()
        self.bot_config_service = bot_config_service or BotConfigService()
        self.observability = observability or Observability()
        # Map intents by id for quick lookup
        self.intents: Dict[str, IntentModel] = {intent.intent_id: intent for intent in intents}

    @classmethod
    async def from_config(
        cls,
        memory_saver: Optional[MemorySaver] = None,
        intents_loader: Optional[Callable[[], Any]] = None,
        nlu_service: Optional[NLUService] = None,
        api_service: Optional[APIService] = None,
        bot_config_service: Optional[BotConfigService] = None,
        observability: Optional[Observability] = None,
    ) -> "DialogueManager":
        """Create a DialogueManager from system defaults while allowing injection.

        Accepts optional injected dependencies for better testability. When omitted,
        defaults are resolved lazily.
        """
        # Load intents (paginate if underlying loader supports it). Keep a simple default
        if intents_loader is None:
            from app.admin.intents.store import list_intents as _default_list_intents

            intents_loader = _default_list_intents

        try:
            db_intents = await intents_loader()
        except Exception as e:
            logger.error("Failed to load intents: %s", e)
            db_intents = []

        intents = [IntentModel.from_db(intent) for intent in db_intents]

        # Bot configuration
        bot_cfg_service = bot_config_service or BotConfigService()
        bot = await bot_cfg_service.get("default")

        # Determine threshold: allow per-bot override, otherwise use global
        try:
            confidence_threshold = getattr(bot, "nlu_config", {}).get("traditional_settings", {}).get("intent_detection_threshold")
            if confidence_threshold is None:
                from app.config import app_config as _app_config

                confidence_threshold = _app_config.DEFAULT_FALLBACK_INTENT_NAME and getattr(_app_config, "DEFAULT_INTENT_CONFIDENCE", 0.5)
        except Exception:
            # fallback hard-coded
            confidence_threshold = 0.5

        fallback_intent_id = getattr(bot, "fallback_intent_name", None) or "fallback"

        # If no memory_saver was provided, the caller must provide one; keep backwards compatibility
        if memory_saver is None:
            raise DialogueManagerException("memory_saver must be provided to initialize DialogueManager")

        return cls(
            memory_saver=memory_saver,
            intents=intents,
            nlu_service=nlu_service or NLUService(),
            slot_service=SlotFillingService(),
            api_service=api_service or APIService(),
            bot_config_service=bot_cfg_service,
            observability=observability or Observability(),
        )

    async def process(self, message: UserMessage) -> State:
        """Main entry - process a single user message and return the updated conversation state.

        This function adds lightweight observability around major phases to help
        identify bottlenecks.
        """
        # Step 1: Load or create state
        self.observability.incr("request.received")

        current_state = await self.memory_saver.get(message.thread_id)

        if not current_state:
            logger.debug("creating new state for thread_id=%s", message.thread_id)
            current_state = await self.memory_saver.init_state(message.thread_id)

        current_state.update(message)

        bot_id = "default"

        # Step 2: NLU processing
        with self.observability.trace("nlu.process"):
            nlu_pipeline = await self.nlu_service.get_pipeline(bot_id)
            if nlu_pipeline is None:
                raise DialogueManagerException("NLU pipeline is not available. Please build the models.")

            # NLU pipeline may throw; keep original contract of pipeline.process
            nlu_result = nlu_pipeline.process({"text": current_state.user_message.text})

        # Step 3: Intent selection
        with self.observability.trace("intent.selection"):
            query_intent_id, _confidence = self._get_intent_id_and_confidence(current_state, nlu_result)

            query_intent = self._get_intent(query_intent_id) or self._get_fallback_intent()

            current_state.nlu = {"entities": nlu_result.get("entities"), "intent": nlu_result.get("intent")}

            active_intent_id = current_state.get_active_intent_id()
            if active_intent_id and query_intent_id != active_intent_id:
                active_intent = self._get_intent(current_state.intent["id"])
            else:
                active_intent = query_intent

        # Step 4: Slot filling / parameter extraction
        with self.observability.trace("slot_filling"):
            current_state, active_intent = self.slot_service.process_intent(query_intent, active_intent, current_state)
            current_state.intent = {"id": active_intent.intent_id}

        # Step 5: API trigger if intent complete
        if current_state.complete:
            with self.observability.trace("api.trigger"):
                request_id = getattr(message, "request_id", None) or message.thread_id
                try:
                    result = await self.api_service.call_intent_api(active_intent, current_state, request_id=request_id)
                    template = Template(active_intent.speech_response, undefined=SilentUndefined, enable_async=True)
                    rendered_text = await template.render_async(context=current_state.context, parameters=current_state.extracted_parameters, result=result)
                    current_state.bot_message = [{"text": msg} for msg in split_sentence(rendered_text)]
                except DialogueManagerException as e:
                    logger.warning("API handling failed: %s", e)
                    current_state.bot_message = [{"text": "Service is not available. Please try again later."}]

        # Persist state and finish
        await self.memory_saver.save(message.thread_id, current_state)
        self.observability.incr("request.processed")
        logger.debug("Processed thread_id=%s", current_state.thread_id, extra=current_state.to_dict())
        return current_state

    def _get_intent_id_and_confidence(self, current_state: State, nlu_result: Dict) -> Tuple[str, float]:
        """Determine intent id from text commands or NLU prediction.

        If NLU confidence is below threshold the fallback intent id is returned.
        """
        input_text = current_state.user_message.text
        if input_text.startswith("/"):
            intent_id = input_text.split("/")[1]
            return intent_id, 1.0

        predicted = nlu_result.get("intent", {})
        confidence = predicted.get("confidence", 0.0)

        # dynamic per-bot threshold could be implemented later; for now use a conservative value
        threshold = 0.5
        if confidence < threshold:
            return self._get_fallback_intent().intent_id, 1.0
        return predicted.get("intent"), confidence

    def _get_intent(self, intent_id: str) -> Optional[IntentModel]:
        return self.intents.get(intent_id)

    def _get_fallback_intent(self) -> IntentModel:
        # Attempt to pick fallback intent from loaded intents, otherwise raise
        return self.intents.get("fallback") or next(iter(self.intents.values()))