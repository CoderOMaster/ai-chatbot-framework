import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from jinja2 import Template

from app.admin.bots.store import BotRepository
from app.admin.intents.store import IntentRepository
from app.bot.memory import MemorySaver
from app.bot.memory.models import State
from app.bot.nlu.pipeline import NLUPipeline
from app.bot.dialogue_manager.http_client import (
    APICallExcetion,
    HTTPResponse,
    call_api,
)
from app.bot.dialogue_manager.models import (
    IntentModel,
    ParameterModel,
    UserMessage,
)
from app.bot.dialogue_manager.utils import SilentUndefined, split_sentence

logger = logging.getLogger("dialogue_manager")

AsyncAPICaller = Callable[
    [
        str,
        str,
        Optional[Dict[str, str]],
        Optional[Dict[str, Any]],
        bool,
    ],
    Awaitable[HTTPResponse],
]


@dataclass(frozen=True)
class DialogueManagerConfig:
    """Configuration values needed to bootstrap the dialogue manager service."""

    fallback_intent_id: str
    bot_name: str = "default"
    intent_confidence_threshold: Optional[float] = None


class DialogueManagerException(Exception):
    pass


class DialogueManager:
    def __init__(
        self,
        memory_saver: MemorySaver,
        intents: List[IntentModel],
        nlu_pipeline: NLUPipeline,
        fallback_intent_id: str,
        intent_confidence_threshold: float,
        api_caller: AsyncAPICaller = call_api,
    ) -> None:
        self.memory_saver = memory_saver
        self.nlu_pipeline: Optional[NLUPipeline] = nlu_pipeline
        self.intents = {intent.intent_id: intent for intent in intents}
        self.fallback_intent_id = fallback_intent_id
        self.confidence_threshold = intent_confidence_threshold
        self._api_caller = api_caller

    @classmethod
    async def from_config(
        cls,
        *,
        intent_repository: IntentRepository,
        bot_repository: BotRepository,
        memory_saver: MemorySaver,
        nlu_pipeline: NLUPipeline,
        config: DialogueManagerConfig,
        api_caller: AsyncAPICaller = call_api,
    ) -> "DialogueManager":
        """Create a dialogue manager using externally provided dependencies."""

        db_intents = await intent_repository.list_intents()
        intents = [IntentModel.from_db(intent) for intent in db_intents]

        bot = await bot_repository.get_bot(config.bot_name)
        confidence_threshold = (
            config.intent_confidence_threshold
            if config.intent_confidence_threshold is not None
            else bot.nlu_config.traditional_settings.intent_detection_threshold
        )

        return cls(
            memory_saver,
            intents,
            nlu_pipeline,
            config.fallback_intent_id,
            confidence_threshold,
            api_caller=api_caller,
        )

    def update_model(self, models_dir: str) -> None:
        """Reload pipeline artifacts after new models are available."""

        if not self.nlu_pipeline:
            logger.warning("Update requested but NLU pipeline is not initialized")
            return

        ok = self.nlu_pipeline.load(models_dir)
        if not ok:
            self.nlu_pipeline = None
        logger.info("NLU Pipeline models updated")

    async def process(self, message: UserMessage) -> State:
        """Process a user message and return the resulting conversation state."""

        if self.nlu_pipeline is None:
            raise DialogueManagerException(
                "NLU pipeline is not initialized. Please build the models."
            )

        current_state = await self.memory_saver.get(message.thread_id)

        if not current_state:
            logger.debug(
                f"No current state found for thread_id: {message.thread_id}, creating new state"
            )
            current_state = await self.memory_saver.init_state(message.thread_id)

        current_state.update(message)

        try:
            nlu_result = self.nlu_pipeline.process(
                {"text": current_state.user_message.text}
            )

            query_intent_id, _ = self._get_intent_id_and_confidence(
                current_state, nlu_result
            )

            query_intent = self._get_intent(query_intent_id)
            if query_intent is None:
                query_intent = self._get_fallback_intent()

            current_state.nlu = {
                "entities": nlu_result.get("entities"),
                "intent": nlu_result.get("intent"),
            }

            active_intent_id = current_state.get_active_intent_id()
            if active_intent_id and query_intent_id != active_intent_id:
                active_intent = self._get_intent(current_state.intent["id"])
            else:
                active_intent = query_intent

            current_state, active_intent = self._process_intent(
                query_intent,
                active_intent,
                current_state,
            )
            current_state.intent = {"id": active_intent.intent_id}

            if current_state.complete:
                current_state = await self._handle_api_trigger(
                    active_intent, current_state
                )

            logger.debug(
                f"Processed input: {current_state.thread_id}",
                extra=current_state.to_dict(),
            )

            await self.memory_saver.save(message.thread_id, current_state)

            return current_state

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            raise

    def _get_intent_id_and_confidence(
        self, current_state: State, nlu_result: Dict
    ) -> Tuple[str, float]:
        """Determine the intent identifier and confidence score for the user input."""

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
        """Return the intent model for the provided identifier."""

        return self.intents.get(intent_id)

    def _get_fallback_intent(self) -> IntentModel:
        """Return the configured fallback intent."""

        return self.intents[self.fallback_intent_id]

    def _process_intent(
        self,
        query_intent: IntentModel,
        active_intent: IntentModel,
        current_state: State,
    ) -> Tuple[State, IntentModel]:
        """Populate slots and manage intent-context state transitions."""

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
            extracted_entities = current_state.nlu.get("entities", {})

            entities_by_type: Dict[str, List[Any]] = {}
            for entity_name, entity_value in extracted_entities.items():
                entities_by_type.setdefault(entity_name, []).append(entity_value)

            if len(current_state.parameters) == 0:
                for param in parameters:
                    current_state.parameters.append(
                        {
                            "name": param.name,
                            "type": param.type,
                            "required": param.required,
                        }
                    )

            for param in parameters:
                if (
                    param.type == "free_text"
                    and current_state.current_node == param.name
                ):
                    current_state.extracted_parameters[param.name] = (
                        current_state.user_message.text
                    )
                    continue

                if param.type in entities_by_type and entities_by_type[param.type]:
                    current_state.extracted_parameters[param.name] = (
                        entities_by_type[param.type].pop(0)
                    )

            current_state = self._handle_missing_parameters(parameters, current_state)

        current_state.complete = not current_state.missing_parameters
        return current_state, active_intent

    def _handle_missing_parameters(
        self, parameters: List[ParameterModel], current_state: State
    ) -> State:
        """Prompt the user for any missing required parameters."""

        current_state.missing_parameters = []
        current_state.current_node = None
        current_state.bot_message = []

        missing_parameters = []

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
        """Invoke an external API if the intent requires it, then render the response."""

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

            except DialogueManagerException as e:
                logger.warning(f"API call failed: {e}")
                current_state.bot_message = [
                    {"text": "Service is not available. Please try again later."}
                ]
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

    async def _call_intent_api(self, intent: IntentModel, current_state: State) -> HTTPResponse:
        """Call the configured API for an intent using the injected HTTP client."""

        api_details = intent.api_details
        headers = api_details.get_headers()
        url_template = Template(api_details.url, undefined=SilentUndefined)
        rendered_url = url_template.render(
            context=current_state.context,
            parameters=current_state.extracted_parameters,
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
            return await self._api_caller(
                rendered_url,
                api_details.request_type,
                headers,
                parameters,
                api_details.is_json,
            )
        except APICallExcetion as e:
            logger.warning(f"API call failed: {e}")
            raise DialogueManagerException("API call failed")