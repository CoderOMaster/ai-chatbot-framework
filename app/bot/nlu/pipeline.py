from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
import os
import copy
import logging

logger = logging.getLogger(__name__)

EventListener = Callable[[str, Dict[str, Any]], None]


class NLUComponent(ABC):
    """Abstract base class for NLU pipeline components.

    Concrete components should implement training, loading and processing
    logic. Implementations must not rely on shared mutable state in the
    incoming message dict since NLUPipeline copies messages between
    components.
    """

    @abstractmethod
    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the component with given training data and persist any
        artifacts to model_path.

        Args:
            training_data: A list of message dictionaries used for training.
            model_path: Filesystem path where component should store its model.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, model_path: str) -> bool:
        """Load component artifacts from model_path.

        Returns:
            True if loading succeeded, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the (possibly augmented) message.

        Implementations should return a new dict or a modified copy of the
        provided message. NLUPipeline will pass a deep copy of the message to
        each component to prevent side-effects across components.
        """
        raise NotImplementedError


class NLUPipeline:
    """Main NLU pipeline that manages ordered execution of components and
    emits lifecycle events for observability.

    The pipeline supports registering event listeners which will be called
    with an event name and a payload dict whenever a component is trained or
    loaded.
    """

    def __init__(self, components: Optional[List[NLUComponent]] = None) -> None:
        """Initialize NLUPipeline.

        Args:
            components: Optional initial list of NLUComponent instances.
        """
        self.components: List[NLUComponent] = components or []
        self._listeners: List[EventListener] = []

    def add_component(self, component: NLUComponent) -> None:
        """Add a component to the pipeline.

        Args:
            component: An instance implementing NLUComponent.
        """
        self.components.append(component)

    def add_event_listener(self, listener: EventListener) -> None:
        """Register an event listener.

        The listener will be called with (event_name, payload) where payload is
        a dict containing event-specific information.
        """
        self._listeners.append(listener)

    def _emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Emit an event to all registered listeners and log it.

        Args:
            event_name: Short name for the event, e.g. 'component_trained'.
            payload: Dictionary with event details.
        """
        logger.debug("Event: %s - %s", event_name, payload)
        for listener in list(self._listeners):
            try:
                listener(event_name, payload)
            except Exception:
                logger.exception("Event listener raised an exception")

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train all components in order and emit 'component_trained' events.

        Ensures the model directory exists.
        """
        os.makedirs(model_path, exist_ok=True)

        for component in self.components:
            comp_name = component.__class__.__name__
            logger.info("Training component %s", comp_name)
            try:
                component.train(training_data, model_path)
                payload = {"component": comp_name, "model_path": model_path}
                self._emit("component_trained", payload)
            except Exception:
                logger.exception("Training failed for component %s", comp_name)
                payload = {"component": comp_name, "model_path": model_path, "error": True}
                self._emit("component_train_failed", payload)
                raise

    def load(self, model_path: str) -> bool:
        """Load all components from model path and emit 'component_loaded' events.

        Returns:
            True if all components loaded successfully, False if any failed.
        """
        all_ok = True
        for component in self.components:
            comp_name = component.__class__.__name__
            logger.info("Loading component %s", comp_name)
            try:
                ok = component.load(model_path)
                payload = {"component": comp_name, "model_path": model_path, "success": bool(ok)}
                if ok:
                    self._emit("component_loaded", payload)
                else:
                    self._emit("component_load_failed", payload)
                    all_ok = False
            except Exception:
                logger.exception("Loading failed for component %s", comp_name)
                payload = {"component": comp_name, "model_path": model_path, "success": False, "error": True}
                self._emit("component_load_failed", payload)
                all_ok = False
        return all_ok

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message through all components in sequence.

        A deep copy of the input message is passed to each component to avoid
        component side-effects leaking across stages. The returned message from
        each component becomes the input to the next.

        Args:
            message: Input message dictionary.

        Returns:
            The resulting message dictionary after all components have processed it.
        """
        current_message: Dict[str, Any] = copy.deepcopy(message)
        for component in self.components:
            comp_name = component.__class__.__name__
            logger.debug("Processing with component %s", comp_name)
            try:
                # Each component receives a deep copy to avoid unintended shared-state
                input_msg = copy.deepcopy(current_message)
                result = component.process(input_msg)
                if result is None:
                    # If a component returns None, keep the current message to avoid breaking the pipeline
                    logger.warning("Component %s returned None; keeping previous message", comp_name)
                else:
                    current_message = result
            except Exception:
                logger.exception("Processing failed in component %s", comp_name)
                # Continue to next component to allow best-effort processing
        return current_message