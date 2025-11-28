from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol, Sequence, TypedDict, Union, runtime_checkable
import os


class IntentRankingItem(TypedDict, total=False):
    intent: str
    confidence: float


class MessagePayload(TypedDict, total=False):
    text: str
    intent: Union[str, Dict[str, Any]]
    intent_ranking: List[IntentRankingItem]
    entities: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    spacy_doc: Any


class TrainingExample(TypedDict, total=False):
    text: str
    intent: str
    entities: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    spacy_doc: Any


TrainingDataset = Sequence[TrainingExample]


@runtime_checkable
class ModelStorage(Protocol):
    def get_model_path(self) -> str:
        """Return the filesystem path where model artifacts should be stored or loaded from."""
        ...


ModelStorageLocation = Union[str, os.PathLike[str], ModelStorage]


def _resolve_model_path(storage: ModelStorageLocation) -> str:
    """Normalize the provided storage location to a concrete filesystem path."""

    if isinstance(storage, ModelStorage):
        return storage.get_model_path()

    return os.fspath(storage)


class NLUComponent(ABC):
    """Abstract base class for NLU pipeline components."""

    @abstractmethod
    def train(self, training_data: TrainingDataset, model_path: str) -> None:
        """Train the component with a sequence of training examples and dump artifacts to `model_path`."""
        pass

    @abstractmethod
    def load(self, model_path: str) -> bool:
        """Load component artifacts from the filesystem path returned by the storage abstraction."""
        pass

    @abstractmethod
    def process(self, message: MessagePayload) -> MessagePayload:
        """Process a message payload and return mutated state for downstream steps."""
        pass


class NLUPipeline:
    """Main NLU pipeline that manages components and their execution order."""

    def __init__(self, components: Optional[List[NLUComponent]] = None):
        """Initialize NLU pipeline with optional list of components."""
        self.components = components or []

    def add_component(self, component: NLUComponent) -> None:
        """Append a component to the execution pipeline."""
        self.components.append(component)

    def train(self, training_data: TrainingDataset, model_storage: ModelStorageLocation) -> None:
        """Train all components using the provided training dataset and storage destination."""
        model_path = _resolve_model_path(model_storage)

        if not isinstance(model_storage, ModelStorage):
            os.makedirs(model_path, exist_ok=True)

        for component in self.components:
            component.train(training_data, model_path)

    def load(self, model_storage: ModelStorageLocation) -> bool:
        """Load all components from the resolved storage path."""
        model_path = _resolve_model_path(model_storage)

        for component in self.components:
            if not component.load(model_path):
                return False
        return True

    def process(self, message: MessagePayload) -> MessagePayload:
        """Run the pipeline over a message payload, threading state through each component."""
        for component in self.components:
            message = component.process(message)
        return message