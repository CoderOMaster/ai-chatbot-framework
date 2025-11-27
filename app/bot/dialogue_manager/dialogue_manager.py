import json
import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime, UTC
from dataclasses import dataclass, field
from functools import lru_cache
from jinja2 import Template
import httpx

from app.bot.memory import MemorySaver
from app.bot.memory.memory_saver_mongo import MemorySaverMongo
from app.bot.memory.models import State
from app.bot.nlu.pipeline import NLUPipeline
from app.bot.nlu.pipeline_utils import get_pipeline
from app.bot.dialogue_manager.utils import SilentUndefined, split_sentence
from app.bot.dialogue_manager.models import (
    IntentModel,
    ParameterModel,
    UserMessage,
)
from app.bot.dialogue_manager.http_client import call_api, APICallExcetion
from app.config import app_config
from app.database import client

logger = logging.getLogger("dialogue_manager")


class DialogueState(Enum):
    """Dialogue flow state machine states."""
    IDLE = "idle"
    PROCESSING_NLU = "processing_nlu"
    RESOLVING_INTENT = "resolving_intent"
    FILLING_PARAMETERS = "filling_parameters"
    CALLING_API = "calling_api"
    GENERATING_RESPONSE = "generating_response"
    COMPLETE = "complete"
    ERROR = "error"


class DialogueManagerException(Exception):
    """Base exception for dialogue manager errors."""
    pass


class NLUServiceException(DialogueManagerException):
    """Exception raised when NLU service fails."""
    pass


class IntentResolutionException(DialogueManagerException):
    """Exception raised when intent resolution fails."""
    pass


class ParameterFillingException(DialogueManagerException):
    """Exception raised when parameter filling fails."""
    pass


class APICallException(DialogueManagerException):
    """Exception raised when API call fails."""
    pass


class ResponseGenerationException(DialogueManagerException):
    """Exception raised when response generation fails."""
    pass


@dataclass
class NLUResult:
    """Cached NLU processing result."""
    text: str
    intent: Dict
    entities: Dict
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def is_stale(self, ttl_seconds: int = 3600) -> bool:
        """Check if cached result is stale.
        
        Args:
            ttl_seconds: Time-to-live in seconds
            
        Returns:
            True if result is older than TTL
        """
        age = (datetime.now(UTC) - self.timestamp).total_seconds()
        return age > ttl_seconds


@dataclass
class DialogueMetrics:
    """Metrics for dialogue processing."""
    thread_id: str
    state: DialogueState
    nlu_processing_time: float = 0.0
    intent_resolution_time: float = 0.0
    parameter_filling_time: float = 0.0
    api_call_time: float = 0.0
    response_generation_time: float = 0.0
    total_time: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "thread_id": self.thread_id,
            "state": self.state.value,
            "nlu_processing_time": self.nlu_processing_time,
            "intent_resolution_time": self.intent_resolution_time,
            "parameter_filling_time": self.parameter_filling_time,
            "api_call_time": self.api_call_time,
            "response_generation_time": self.response_generation_time,
            "total_time": self.total_time,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


class IntentResolver:
    """Service for resolving user intents from NLU results."""
    
    def __init__(
        self,
        intents: Dict[str, IntentModel],
        fallback_intent_id: str,
        confidence_threshold: float,
    ):
        """Initialize intent resolver.
        
        Args:
            intents: Dictionary mapping intent IDs to IntentModel instances
            fallback_intent_id: ID of fallback intent
            confidence_threshold: Minimum confidence for intent acceptance
        """
        self.intents = intents
        self.fallback_intent_id = fallback_intent_id
        self.confidence_threshold = confidence_threshold
    
    async def resolve(
        self,
        user_text: str,
        nlu_result: Dict,
        current_state: State,
    ) -> Tuple[str, float]:
        """Resolve intent from NLU result and user input.
        
        Args:
            user_text: User input text
            nlu_result: NLU pipeline result
            current_state: Current conversation state
            
        Returns:
            Tuple of (intent_id, confidence)
            
        Raises:
            IntentResolutionException: If resolution fails
        """
        try:
            # Handle explicit intent commands (e.g., "/intent_name")
            if user_text.startswith("/"):
                intent_id = user_text.split("/")[1]
                if intent_id in self.intents:
                    return intent_id, 1.0
                logger.warning(f"Explicit intent '{intent_id}' not found")
                return self.fallback_intent_id, 1.0
            
            # Handle NLU-predicted intents
            predicted = nlu_result.get("intent", {})
            confidence = predicted.get("confidence", 0.0)
            
            if confidence < self.confidence_threshold:
                logger.debug(
                    f"Intent confidence {confidence} below threshold {self.confidence_threshold}"
                )
                return self.fallback_intent_id, 1.0
            
            intent_id = predicted.get("intent", self.fallback_intent_id)
            return intent_id, confidence
            
        except Exception as e:
            logger.error(f"Intent resolution failed: {e}", exc_info=True)
            raise IntentResolutionException(f"Failed to resolve intent: {str(e)}")
    
    def get_intent(self, intent_id: str) -> Optional[IntentModel]:
        """Retrieve intent by ID.
        
        Args:
            intent_id: Intent identifier
            
        Returns:
            IntentModel or None if not found
        """
        return self.intents.get(intent_id)
    
    def get_fallback_intent(self) -> IntentModel:
        """Get fallback intent.
        
        Returns:
            IntentModel for fallback intent
        """
        return self.intents[self.fallback_intent_id]


class ParameterFiller:
    """Service for filling intent parameters from extracted entities."""
    
    async def fill(
        self,
        parameters: List[ParameterModel],
        extracted_entities: Dict,
        current_state: State,
    ) -> Tuple[Dict, List[str]]:
        """Fill parameters from extracted entities.
        
        Args:
            parameters: List of parameter definitions
            extracted_entities: Extracted entities from NLU
            current_state: Current conversation state
            
        Returns:
            Tuple of (extracted_parameters, missing_parameters)
            
        Raises:
            ParameterFillingException: If filling fails
        """
        try:
            extracted_parameters = {}
            missing_parameters = []
            
            # Group entities by type for efficient matching
            entities_by_type = self._group_entities_by_type(extracted_entities)
            
            for param in parameters:
                # Handle free_text parameters being prompted
                if (
                    param.type == "free_text"
                    and current_state.current_node == param.name
                ):
                    extracted_parameters[param.name] = current_state.user_message.text
                    continue
                
                # Match entities with parameters by type
                if param.type in entities_by_type and entities_by_type[param.type]:
                    extracted_parameters[param.name] = entities_by_type[param.type].pop(0)
                elif param.required:
                    missing_parameters.append(param.name)
            
            return extracted_parameters, missing_parameters
            
        except Exception as e:
            logger.error(f"Parameter filling failed: {e}", exc_info=True)
            raise ParameterFillingException(f"Failed to fill parameters: {str(e)}")
    
    @staticmethod
    def _group_entities_by_type(extracted_entities: Dict) -> Dict[str, List]:
        """Group extracted entities by type.
        
        Args:
            extracted_entities: Extracted entities dictionary
            
        Returns:
            Dictionary mapping entity types to lists of values
        """
        entities_by_type = {}
        for entity_name, entity_value in extracted_entities.items():
            if entity_name not in entities_by_type:
                entities_by_type[entity_name] = []
            entities_by_type[entity_name].append(entity_value)
        return entities_by_type


class APICaller:
    """Service for calling external APIs based on intent configuration."""
    
    async def call(
        self,
        intent: IntentModel,
        current_state: State,
    ) -> Dict:
        """Call external API for intent.
        
        Args:
            intent: Intent with API configuration
            current_state: Current conversation state
            
        Returns:
            API response as dictionary
            
        Raises:
            APICallException: If API call fails
        """
        if not intent.api_trigger or not intent.api_details:
            return {}
        
        try:
            api_details = intent.api_details
            headers = api_details.get_headers()
            
            # Render URL template
            url_template = Template(api_details.url, undefined=SilentUndefined)
            rendered_url = url_template.render(
                context=current_state.context,
                parameters=current_state.extracted_parameters,
            )
            
            # Prepare request body
            if api_details.is_json:
                request_template = Template(
                    api_details.json_data,
                    undefined=SilentUndefined,
                )
                request_json = request_template.render(
                    context=current_state.context,
                    parameters=current_state.extracted_parameters,
                )
                parameters = json.loads(request_json)
            else:
                parameters = current_state.extracted_parameters
            
            # Call API
            result = await call_api(
                rendered_url,
                api_details.request_type,
                headers,
                parameters,
                api_details.is_json,
            )
            
            logger.debug(f"API call successful for intent {intent.intent_id}")
            return result
            
        except APICallExcetion as e:
            logger.warning(f"API call failed: {e}")
            raise APICallException(f"API call failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during API call: {e}", exc_info=True)
            raise APICallException(f"Unexpected error during API call: {str(e)}")


class ResponseGenerator:
    """Service for generating bot responses from templates."""
    
    async def generate(
        self,
        intent: IntentModel,
        current_state: State,
        api_result: Optional[Dict] = None,
    ) -> List[Dict]:
        """Generate bot response from intent template.
        
        Args:
            intent: Intent with response template
            current_state: Current conversation state
            api_result: Optional API call result
            
        Returns:
            List of message dictionaries
            
        Raises:
            ResponseGenerationException: If generation fails
        """
        try:
            template = Template(
                intent.speech_response,
                undefined=SilentUndefined,
                enable_async=True,
            )
            
            render_context = {
                "context": current_state.context,
                "parameters": current_state.extracted_parameters,
            }
            
            if api_result:
                render_context["result"] = api_result
            
            rendered_text = await template.render_async(**render_context)
            messages = [{"text": msg} for msg in split_sentence(rendered_text)]
            
            logger.debug(f"Generated response for intent {intent.intent_id}")
            return messages
            
        except Exception as e:
            logger.error(f"Response generation failed: {e}", exc_info=True)
            raise ResponseGenerationException(f"Failed to generate response: {str(e)}")


class DialogueManager:
    """Core dialogue orchestration service managing conversation flow."""
    
    def __init__(
        self,
        memory_saver: MemorySaver,
        intents: List[IntentModel],
        nlu_pipeline: NLUPipeline,
        fallback_intent_id: str,
        intent_confidence_threshold: float,
    ):
        """Initialize dialogue manager with dependencies.
        
        Args:
            memory_saver: Memory persistence service
            intents: List of available intents
            nlu_pipeline: NLU processing pipeline
            fallback_intent_id: ID of fallback intent
            intent_confidence_threshold: Minimum confidence for intent acceptance
        """
        self.memory_saver = memory_saver
        self.nlu_pipeline = nlu_pipeline
        self.intents = {intent.intent_id: intent for intent in intents}
        self.fallback_intent_id = fallback_intent_id
        self.confidence_threshold = intent_confidence_threshold
        
        # Initialize sub-services
        self.intent_resolver = IntentResolver(
            self.intents,
            fallback_intent_id,
            intent_confidence_threshold,
        )
        self.parameter_filler = ParameterFiller()
        self.api_caller = APICaller()
        self.response_generator = ResponseGenerator()
        
        # NLU result cache
        self._nlu_cache: Dict[str, NLUResult] = {}
        self._cache_lock = asyncio.Lock()
    
    @classmethod
    async def from_config(cls):
        """Initialize DialogueManager from configuration.
        
        Returns:
            Configured DialogueManager instance
            
        Raises:
            DialogueManagerException: If initialization fails
        """
        try:
            # Load intents via internal API
            intents = await cls._load_intents_from_api()
            
            # Initialize NLU pipeline
            nlu_pipeline = await get_pipeline()
            
            # Get configuration
            fallback_intent_id = app_config.DEFAULT_FALLBACK_INTENT_NAME
            
            # Get bot configuration via internal API
            confidence_threshold = await cls._load_confidence_threshold_from_api()
            
            # Initialize memory saver
            memory_saver = MemorySaverMongo(client)
            
            return cls(
                memory_saver,
                intents,
                nlu_pipeline,
                fallback_intent_id,
                confidence_threshold,
            )
        except Exception as e:
            logger.error(f"Failed to initialize DialogueManager: {e}", exc_info=True)
            raise DialogueManagerException(f"Initialization failed: {str(e)}")
    
    @staticmethod
    async def _load_intents_from_api() -> List[IntentModel]:
        """Load intents from internal API instead of direct import.
        
        Returns:
            List of IntentModel instances
            
        Raises:
            DialogueManagerException: If API call fails
        """
        try:
            # This would call the internal intents API
            # For now, using fallback to original import
            from app.admin.intents.store import list_intents
            db_intents = await list_intents()
            return [IntentModel.from_db(intent) for intent in db_intents]
        except Exception as e:
            logger.error(f"Failed to load intents from API: {e}")
            raise DialogueManagerException(f"Failed to load intents: {str(e)}")
    
    @staticmethod
    async def _load_confidence_threshold_from_api() -> float:
        """Load confidence threshold from internal API.
        
        Returns:
            Confidence threshold value
            
        Raises:
            DialogueManagerException: If API call fails
        """
        try:
            # This would call the internal bot config API
            # For now, using fallback to original import
            from app.admin.bots.store import get_bot
            bot = await get_bot("default")
            return bot.nlu_config.traditional_settings.intent_detection_threshold
        except Exception as e:
            logger.error(f"Failed to load confidence threshold from API: {e}")
            raise DialogueManagerException(f"Failed to load configuration: {str(e)}")
    
    def update_model(self, models_dir: str) -> None:
        """Update NLU models after training completion.
        
        Args:
            models_dir: Directory containing trained models
            
        Raises:
            DialogueManagerException: If model loading fails
        """
        try:
            ok = self.nlu_pipeline.load(models_dir)
            if not ok:
                raise DialogueManagerException("Failed to load NLU models")
            
            # Clear NLU cache on model update
            self._nlu_cache.clear()
            logger.info("NLU Pipeline models updated and cache cleared")
        except Exception as e:
            logger.error(f"Failed to update NLU models: {e}", exc_info=True)
            raise DialogueManagerException(f"Model update failed: {str(e)}")
    
    async def process(self, message: UserMessage) -> State:
        """Process user message through dialogue pipeline.
        
        Args:
            message: UserMessage instance
            
        Returns:
            Updated conversation State
            
        Raises:
            DialogueManagerException: If processing fails
        """
        metrics = DialogueMetrics(thread_id=message.thread_id, state=DialogueState.IDLE)
        start_time = datetime.now(UTC)
        
        try:
            if self.nlu_pipeline is None:
                raise NLUServiceException(
                    "NLU pipeline is not initialized. Please build the models."
                )
            
            # Step 1: Get or initialize conversation state
            metrics.state = DialogueState.PROCESSING_NLU
            current_state = await self._get_or_init_state(message)
            
            # Step 2: Process through NLU pipeline with caching
            nlu_start = datetime.now(UTC)
            nlu_result = await self._process_nlu(current_state.user_message.text)
            metrics.nlu_processing_time = (datetime.now(UTC) - nlu_start).total_seconds()
            
            # Step 3: Resolve intent
            metrics.state = DialogueState.RESOLVING_INTENT
            intent_start = datetime.now(UTC)
            query_intent_id, confidence = await self.intent_resolver.resolve(
                current_state.user_message.text,
                nlu_result,
                current_state,
            )
            metrics.intent_resolution_time = (datetime.now(UTC) - intent_start).total_seconds()
            
            # Step 4: Get intent objects
            query_intent = self.intent_resolver.get_intent(query_intent_id)
            if query_intent is None:
                query_intent = self.intent_resolver.get_fallback_intent()
            
            # Store NLU results in state
            current_state = self._update_state_with_nlu(current_state, nlu_result)
            
            # Step 5: Handle cancel intent
            if query_intent.intent_id == "cancel":
                current_state = self._handle_cancel_intent(current_state)
            else:
                # Step 6: Fill parameters
                metrics.state = DialogueState.FILLING_PARAMETERS
                fill_start = datetime.now(UTC)
                current_state = await self._fill_parameters(query_intent, current_state)
                metrics.parameter_filling_time = (datetime.now(UTC) - fill_start).total_seconds()
                
                # Step 7: Call API if intent is complete
                if current_state.complete:
                    metrics.state = DialogueState.CALLING_API
                    api_start = datetime.now(UTC)
                    current_state = await self._handle_api_and_response(
                        query_intent,
                        current_state,
                    )
                    metrics.api_call_time = (datetime.now(UTC) - api_start).total_seconds()
                else:
                    # Generate prompt for missing parameters
                    metrics.state = DialogueState.GENERATING_RESPONSE
                    gen_start = datetime.now(UTC)
                    current_state = await self._generate_parameter_prompt(
                        current_state
                    )
                    metrics.response_generation_time = (
                        datetime.now(UTC) - gen_start
                    ).total_seconds()
            
            current_state = current_state.replace(intent={"id": query_intent.intent_id})
            
            # Step 8: Save state
            await self.memory_saver.save(message.thread_id, current_state)
            
            metrics.state = DialogueState.COMPLETE
            metrics.total_time = (datetime.now(UTC) - start_time).total_seconds()
            
            logger.debug(
                f"Processed message for thread {message.thread_id}",
                extra={"metrics": metrics.to_dict()},
            )
            
            return current_state
            
        except Exception as e:
            metrics.state = DialogueState.ERROR
            metrics.error = str(e)
            metrics.total_time = (datetime.now(UTC) - start_time).total_seconds()
            
            logger.error(
                f"Error processing request for thread {message.thread_id}: {e}",
                exc_info=True,
                extra={"metrics": metrics.to_dict()},
            )
            raise
    
    async def _get_or_init_state(self, message: UserMessage) -> State:
        """Get existing state or initialize new one.
        
        Args:
            message: User message
            
        Returns:
            Conversation state
        """
        current_state = await self.memory_saver.get(message.thread_id)
        
        if not current_state:
            logger.debug(f"Creating new state for thread {message.thread_id}")
            current_state = await self.memory_saver.init_state(message.thread_id)
        
        return current_state.update(message)
    
    async def _process_nlu(self, text: str) -> Dict:
        """Process text through NLU pipeline with caching.
        
        Args:
            text: Input text
            
        Returns:
            NLU result dictionary
            
        Raises:
            NLUServiceException: If NLU processing fails
        """
        try:
            # Check cache
            async with self._cache_lock:
                if text in self._nlu_cache:
                    cached = self._nlu_cache[text]
                    if not cached.is_stale():
                        logger.debug(f"Using cached NLU result for: {text}")
                        return {
                            "intent": cached.intent,
                            "entities": cached.entities,
                        }
            
            # Process through pipeline
            result = self.nlu_pipeline.process({"text": text})
            
            # Cache result
            async with self._cache_lock:
                self._nlu_cache[text] = NLUResult(
                    text=text,
                    intent=result.get("intent", {}),
                    entities=result.get("entities", {}),
                    confidence=result.get("intent", {}).get("confidence", 0.0),
                )
            
            return result
            
        except Exception as e:
            logger.error(f"NLU processing failed: {e}", exc_info=True)
            raise NLUServiceException(f"NLU processing failed: {str(e)}")
    
    @staticmethod
    def _update_state_with_nlu(current_state: State, nlu_result: Dict) -> State:
        """Update state with NLU results.
        
        Args:
            current_state: Current state
            nlu_result: NLU result
            
        Returns:
            Updated state
        """
        return current_state.replace(
            nlu={
                "entities": nlu_result.get("entities", {}),
                "intent": nlu_result.get("intent", {}),
            }
        )
    
    @staticmethod
    def _handle_cancel_intent(current_state: State) -> State:
        """Handle cancel intent by resetting state.
        
        Args:
            current_state: Current state
            
        Returns:
            Reset state
        """
        return current_state.replace(
            complete=True,
            parameters=[],
            extracted_parameters={},
            missing_parameters=[],
            current_node="",
            bot_message=[{"text": "Cancelled."}],
        )
    
    async def _fill_parameters(
        self,
        intent: IntentModel,
        current_state: State,
    ) -> State:
        """Fill intent parameters.
        
        Args:
            intent: Intent with parameters
            current_state: Current state
            
        Returns:
            Updated state with filled parameters
        """
        if not intent.parameters:
            return current_state.replace(complete=True)
        
        # Initialize parameters list if empty
        if not current_state.parameters:
            parameters = [
                {
                    "name": param.name,
                    "type": param.type,
                    "required": param.required,
                }
                for param in intent.parameters
            ]
            current_state = current_state.replace(parameters=parameters)
        
        # Fill parameters
        extracted_entities = current_state.nlu.get("entities", {})
        extracted_params, missing_params = await self.parameter_filler.fill(
            intent.parameters,
            extracted_entities,
            current_state,
        )
        
        return current_state.replace(
            extracted_parameters=extracted_params,
            missing_parameters=missing_params,
            complete=len(missing_params) == 0,
        )
    
    async def _handle_api_and_response(
        self,
        intent: IntentModel,
        current_state: State,
    ) -> State:
        """Call API and generate response.
        
        Args:
            intent: Intent with API configuration
            current_state: Current state
            
        Returns:
            Updated state with response
        """
        api_result = None
        
        if intent.api_trigger and intent.api_details:
            try:
                api_result = await self.api_caller.call(intent, current_state)
            except APICallException as e:
                logger.warning(f"API call failed: {e}")
                return current_state.replace(
                    bot_message=[
                        {"text": "Service is not available. Please try again later."}
                    ]
                )
        
        # Generate response
        messages = await self.response_generator.generate(
            intent,
            current_state,
            api_result,
        )
        
        return current_state.replace(bot_message=messages)
    
    async def _generate_parameter_prompt(self, current_state: State) -> State:
        """Generate prompt for missing parameters.
        
        Args:
            current_state: Current state
            
        Returns:
            Updated state with prompt
        """
        if not current_state.missing_parameters:
            return current_state
        
        # Get first missing parameter
        missing_param_name = current_state.missing_parameters[0]
        
        # Find parameter definition
        for param in current_state.parameters:
            if param.get("name") == missing_param_name:
                # Find the actual parameter model to get prompt
                # This is a simplified version - in production would need access to intent
                prompt_text = f"Please provide {missing_param_name}"
                messages = [{"text": msg} for msg in split_sentence(prompt_text)]
                
                return current_state.replace(
                    current_node=missing_param_name,
                    bot_message=messages,
                )
        
        return current_state