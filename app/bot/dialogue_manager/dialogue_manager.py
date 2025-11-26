import json
import logging
import time
from typing import Dict, List, Optional, Tuple
from jinja2 import Template
from shared.memory import MemorySaver
from shared.models.memory import State
from shared.nlu.pipeline import NLUPipeline
from shared.utils import SilentUndefined, split_sentence
from shared.models.dialogue import IntentModel, ParameterModel, UserMessage
from shared.utils.http_client import call_api, APICallException
from shared.config import app_config
from shared.database import client
from shared.utils.circuit_breaker import CircuitBreaker
from shared.metrics import metrics

logger = logging.getLogger("dialogue_manager")

# Configuration constants
DEFAULT_CONVERSATION_TIMEOUT_SECONDS = 3600  # 1 hour
DEFAULT_API_CALL_TIMEOUT_SECONDS = 30
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60


class DialogueManagerException(Exception):
    """Exception raised for dialogue manager errors."""
    pass


class DialogueManager:
    """
    Core dialogue manager microservice that orchestrates NLU processing,
    state management, and API triggers for conversational interactions.
    """

    def __init__(
        self,
        memory_saver: MemorySaver,
        intents: List[IntentModel],
        nlu_pipeline: NLUPipeline,
        fallback_intent_id: str,
        intent_confidence_threshold: float,
        conversation_timeout_seconds: int = DEFAULT_CONVERSATION_TIMEOUT_SECONDS,
        api_call_timeout_seconds: int = DEFAULT_API_CALL_TIMEOUT_SECONDS,
    ):
        """
        Initialize DialogueManager with dependency injection.

        Args:
            memory_saver: Instance for persisting conversation state
            intents: List of available intents
            nlu_pipeline: NLU pipeline for intent and entity extraction
            fallback_intent_id: Intent ID to use when confidence is low
            intent_confidence_threshold: Minimum confidence for intent acceptance
            conversation_timeout_seconds: Timeout for inactive conversations
            api_call_timeout_seconds: Timeout for external API calls
        """
        self.memory_saver = memory_saver
        self.nlu_pipeline = nlu_pipeline
        self.intents = {
            intent.intent_id: intent for intent in intents
        }  # Map for faster lookup
        self.fallback_intent_id = fallback_intent_id
        self.confidence_threshold = intent_confidence_threshold
        self.conversation_timeout_seconds = conversation_timeout_seconds
        self.api_call_timeout_seconds = api_call_timeout_seconds

        # Initialize circuit breaker for API calls
        self.api_circuit_breaker = CircuitBreaker(
            failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            recovery_timeout=CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        )

    @classmethod
    async def from_config(
        cls,
        memory_saver: MemorySaver,
        intents: List[IntentModel],
        nlu_pipeline: NLUPipeline,
        fallback_intent_id: Optional[str] = None,
        intent_confidence_threshold: Optional[float] = None,
    ):
        """
        Factory method to initialize DialogueManager with configuration.

        Args:
            memory_saver: Injected memory saver instance
            intents: Injected list of intents
            nlu_pipeline: Injected NLU pipeline instance
            fallback_intent_id: Optional override for fallback intent ID
            intent_confidence_threshold: Optional override for confidence threshold

        Returns:
            Configured DialogueManager instance
        """
        # Use provided values or fall back to config
        fallback_id = fallback_intent_id or app_config.DEFAULT_FALLBACK_INTENT_NAME
        confidence_threshold = (
            intent_confidence_threshold
            or app_config.INTENT_DETECTION_THRESHOLD
        )

        return cls(
            memory_saver=memory_saver,
            intents=intents,
            nlu_pipeline=nlu_pipeline,
            fallback_intent_id=fallback_id,
            intent_confidence_threshold=confidence_threshold,
        )

    def update_model(self, models_dir: str) -> None:
        """
        Signal hook to be called after training is completed.
        Reloads ML models and synonyms.

        Args:
            models_dir: Directory containing trained models
        """
        try:
            ok = self.nlu_pipeline.load(models_dir)
            if not ok:
                logger.error("Failed to load NLU pipeline models")
                self.nlu_pipeline = None
            else:
                logger.info("NLU Pipeline models updated successfully")
                metrics.increment("dialogue_manager.model_update.success")
        except Exception as e:
            logger.error(f"Error updating NLU pipeline models: {e}", exc_info=True)
            metrics.increment("dialogue_manager.model_update.failure")
            raise

    async def process(self, message: UserMessage) -> State:
        """
        Single entry point to process the user message.

        Args:
            message: UserMessage instance containing the request data

        Returns:
            Current state of the conversation including the bot response

        Raises:
            DialogueManagerException: If NLU pipeline is not initialized or processing fails
        """
        start_time = time.time()

        if self.nlu_pipeline is None:
            raise DialogueManagerException(
                "NLU pipeline is not initialized. Please build the models."
            )

        try:
            # Step 1: Get current state
            current_state = await self.memory_saver.get(message.thread_id)

            if not current_state:
                logger.debug(
                    f"No current state found for thread_id: {message.thread_id}, creating new state"
                )
                current_state = await self.memory_saver.init_state(message.thread_id)
            else:
                # Check conversation timeout
                if self._is_conversation_expired(current_state):
                    logger.info(
                        f"Conversation expired for thread_id: {message.thread_id}, resetting state"
                    )
                    current_state = await self.memory_saver.init_state(message.thread_id)
                    metrics.increment("dialogue_manager.conversation_timeout")

            current_state.update(message)

            # Step 2: Process through NLU pipeline
            nlu_result = self.nlu_pipeline.process(
                {"text": current_state.user_message.text}
            )

            # Step 3: Get intent ID and confidence
            query_intent_id, _ = self._get_intent_id_and_confidence(
                current_state, nlu_result
            )

            # Step 4: Retrieve the intent object
            query_intent = self._get_intent(query_intent_id)
            if query_intent is None:
                query_intent = self._get_fallback_intent()

            current_state.nlu = {
                "entities": nlu_result.get("entities"),
                "intent": nlu_result.get("intent"),
            }

            # if query_intent is not the same as active intent,
            # fetch active intent as well
            active_intent_id = current_state.get_active_intent_id()
            if active_intent_id and query_intent_id != active_intent_id:
                active_intent = self._get_intent(current_state.intent["id"])
            else:
                active_intent = query_intent

            # Step 5: Process the intent
            current_state, active_intent = self._process_intent(
                query_intent,
                active_intent,
                current_state,
            )
            current_state.intent = {"id": active_intent.intent_id}

            # Step 6: Handle API trigger if the intent is complete
            if current_state.complete:
                current_state = await self._handle_api_trigger(
                    active_intent, current_state
                )

            logger.debug(
                f"Processed input: {current_state.thread_id}",
                extra=current_state.to_dict(),
            )

            # Step 7: Save the state
            await self.memory_saver.save(message.thread_id, current_state)

            # Record metrics
            processing_time = time.time() - start_time
            metrics.timing("dialogue_manager.process_time", processing_time)
            metrics.increment("dialogue_manager.process.success")

            return current_state

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            metrics.increment("dialogue_manager.process.failure")
            raise

    def _is_conversation_expired(self, state: State) -> bool:
        """
        Check if conversation has exceeded timeout threshold.

        Args:
            state: Current conversation state

        Returns:
            True if conversation has expired, False otherwise
        """
        if not hasattr(state, "last_updated_at") or state.last_updated_at is None:
            return False

        elapsed_seconds = time.time() - state.last_updated_at
        return elapsed_seconds > self.conversation_timeout_seconds

    def _get_intent_id_and_confidence(
        self, current_state: State, nlu_result: Dict
    ) -> Tuple[str, float]:
        """
        Determine the intent ID and confidence based on the request input.

        Args:
            current_state: Current conversation state
            nlu_result: Result from NLU pipeline

        Returns:
            Tuple of (intent_id, confidence_score)
        """
        input_text = current_state.user_message.text
        if input_text.startswith("/"):
            intent_id = input_text.split("/")[1]
            confidence = 1.0
        else:
            predicted = nlu_result["intent"]
            if predicted["confidence"] < self.confidence_threshold:
                return self.fallback_intent_id, 1.0
            else:
                return predicted["intent"], predicted["confidence"]
        return intent_id, confidence

    def _get_intent(self, intent_id: str) -> Optional[IntentModel]:
        """
        Retrieve the intent object by its ID.

        Args:
            intent_id: ID of the intent to retrieve

        Returns:
            IntentModel instance or None if not found
        """
        return self.intents.get(intent_id)

    def _get_fallback_intent(self) -> IntentModel:
        """
        Retrieve the fallback intent.

        Returns:
            IntentModel instance for fallback intent

        Raises:
            DialogueManagerException: If fallback intent is not configured
        """
        fallback = self.intents.get(self.fallback_intent_id)
        if fallback is None:
            raise DialogueManagerException(
                f"Fallback intent '{self.fallback_intent_id}' not found"
            )
        return fallback

    def _process_intent(
        self,
        query_intent: IntentModel,
        active_intent: IntentModel,
        current_state: State,
    ) -> Tuple[State, IntentModel]:
        """
        Process the intent and update the result model
        with extracted parameters and other details.

        Args:
            query_intent: Intent identified from user input
            active_intent: Currently active intent in conversation
            current_state: Current conversation state

        Returns:
            Tuple of (updated_state, active_intent)
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
            entities_by_type = {}
            for entity_name, entity_value in extracted_entities.items():
                if entity_name not in entities_by_type:
                    entities_by_type[entity_name] = []
                entities_by_type[entity_name].append(entity_value)

            # populate parameters
            if len(current_state.parameters) == 0:
                for param in parameters:
                    current_state.parameters.append(
                        {
                            "name": param.name,
                            "type": param.type,
                            "required": param.required,
                        }
                    )

            # Match extracted entities with parameters based on type
            for param in parameters:
                # For free_text parameters being prompted
                if (
                    param.type == "free_text"
                    and current_state.current_node == param.name
                ):
                    current_state.extracted_parameters[param.name] = (
                        current_state.user_message.text
                    )
                    continue
                else:
                    # Get all entities of matching type
                    if param.type in entities_by_type and entities_by_type[param.type]:
                        # Take the next available entity of this type
                        current_state.extracted_parameters[param.name] = (
                            entities_by_type[param.type].pop(0)
                        )

            # Handle missing parameters
            current_state = self._handle_missing_parameters(parameters, current_state)

        # Check if there are no missing parameters
        # to mark the intent as complete
        current_state.complete = not current_state.missing_parameters
        return current_state, active_intent

    def _handle_missing_parameters(
        self, parameters: List[ParameterModel], current_state: State
    ) -> State:
        """
        Handle missing parameters in the result model.

        Args:
            parameters: List of parameters from the intent
            current_state: Current conversation state

        Returns:
            Updated conversation state
        """
        missing_parameters = []
        current_state.missing_parameters = []

        # clear current node
        current_state.current_node = None
        current_state.bot_message = []

        for parameter in parameters:
            if (
                parameter.required
                and parameter.name not in current_state.extracted_parameters
            ):
                current_state.missing_parameters.append(parameter.name)
                missing_parameters.append(parameter)

        if missing_parameters:
            current_node = missing_parameters[0]
            current_state.current_node = current_node.name
            current_state.bot_message = [
                {"text": msg} for msg in split_sentence(current_node.prompt)
            ]
        return current_state

    async def _handle_api_trigger(
        self, intent: IntentModel, current_state: State
    ) -> State:
        """
        Handle API trigger if the intent requires it.

        Args:
            intent: Intent with potential API trigger
            current_state: Current conversation state

        Returns:
            Updated conversation state with bot response
        """
        if intent.api_trigger and intent.api_details:
            try:
                result = await self._call_intent_api(intent, current_state)
                template = Template(
                    intent.speech_response,
                    undefined=SilentUndefined,
                    enable_async=True,
                )
                rendered_text = await template.render_async(
                    context=current_state.context,
                    parameters=current_state.extracted_parameters,
                    result=result,
                )

                current_state.bot_message = [
                    {"text": msg} for msg in split_sentence(rendered_text)
                ]
                metrics.increment("dialogue_manager.api_trigger.success")

            except DialogueManagerException as e:
                logger.warning(f"API call failed: {e}")
                current_state.bot_message = [
                    {"text": "Service is not available. Please try again later."}
                ]
                metrics.increment("dialogue_manager.api_trigger.failure")
        else:
            template = Template(
                intent.speech_response,
                undefined=SilentUndefined,
                enable_async=True,
            )
            rendered_text = await template.render_async(
                context=current_state.context,
                parameters=current_state.extracted_parameters,
            )
            current_state.bot_message = [
                {"text": msg} for msg in split_sentence(rendered_text)
            ]
        return current_state

    async def _call_intent_api(
        self, intent: IntentModel, current_state: State
    ) -> Dict:
        """
        Call the API associated with the intent with circuit breaker protection.

        Args:
            intent: Intent with API configuration
            current_state: Current conversation state

        Returns:
            API response as dictionary

        Raises:
            DialogueManagerException: If API call fails or circuit breaker is open
        """
        if self.api_circuit_breaker.is_open():
            logger.error("API circuit breaker is open, rejecting API call")
            raise DialogueManagerException("API service temporarily unavailable")

        api_details = intent.api_details
        headers = api_details.get_headers()
        url_template = Template(api_details.url, undefined=SilentUndefined)
        rendered_url = url_template.render(
            context=current_state.context, parameters=current_state.extracted_parameters
        )

        if api_details.is_json:
            request_template = Template(
                api_details.json_data, undefined=SilentUndefined
            )
            request_json = request_template.render(
                context=current_state.context,
                parameters=current_state.extracted_parameters,
            )
            parameters = json.loads(request_json)
        else:
            parameters = current_state.extracted_parameters

        try:
            result = await call_api(
                rendered_url,
                api_details.request_type,
                headers,
                parameters,
                api_details.is_json,
                timeout=self.api_call_timeout_seconds,
            )
            self.api_circuit_breaker.record_success()
            return result
        except APICallException as e:
            logger.warning(f"API call failed: {e}")
            self.api_circuit_breaker.record_failure()
            raise DialogueManagerException("API call failed")