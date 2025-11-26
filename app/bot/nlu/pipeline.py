from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TypedDict, Union
import os


class Entity(TypedDict, total=False):
    """Representation of an extracted entity from a message.

    Fields are optional to allow flexible component outputs.
    """
    start: int
    end: int
    value: str
    entity: str
    confidence: float


class MessageDict(TypedDict, total=False):
    """Shape of a runtime message that flows through the NLU pipeline.

    Common keys:
    - text: raw user text
    - intent: predicted intent name
    - intent_ranking: intent candidates with scores
    - entities: list of extracted entities
    - metadata: arbitrary component metadata
    """
    text: str
    intent: Optional[str]
    intent_ranking: Optional[List[Dict[str, Any]]]
    entities: Optional[List[Entity]]
    metadata: Optional[Dict[str, Any]]


class TrainingExample(TypedDict, total=False):
    """Single training example used during component training."""
    text: str
    intent: Optional[str]
    entities: Optional[List[Entity]]


TrainingData = List[TrainingExample]


class ModelStorage(Protocol):
    """Protocol for a pluggable storage abstraction used to save/load model artifacts.

    Implementations can be local filesystem wrappers, cloud object stores, or any
    custom storage backend. The NLUPipeline will pass this object through to
    components; components are expected to know how to interact with the storage
    abstraction they require.
    """

    def exists(self, path: Union[str, os.PathLike]) -> bool: ...

    def makedirs(self, path: Union[str, os.PathLike], exist_ok: bool = True) -> None: ...

    def save_bytes(self, path: Union[str, os.PathLike], data: bytes) -> None: ...

    def load_bytes(self, path: Union[str, os.PathLike]) -> bytes: ...


ModelPath = Union[str, os.PathLike, ModelStorage]


class NLUComponent(ABC):
    """Abstract base class for NLU pipeline components.

    Components should be lightweight, framework-agnostic, and operate on the
    MessageDict shape defined above. The train/load APIs accept either a
    filesystem-like path (str / os.PathLike) or a ModelStorage implementation
    to allow training and inference to operate against different storage
    backends (local fs, S3, etc.) without changing component signatures.
    """

    @abstractmethod
    def train(self, training_data: TrainingData, model_path: ModelPath) -> None:
        """Train the component with the given training data and persist artifacts.

        Args:
            training_data: list of training examples (see TrainingData).
            model_path: either a filesystem path or a ModelStorage instance where
                the component should write its artifacts.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, model_path: ModelPath) -> bool:
        """Load component artifacts from the provided model_path.

        Returns:
            True when load succeeded, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def process(self, message: MessageDict) -> MessageDict:
        """Process an incoming message and return the (possibly) modified message.

        Components should not assume the presence of any keys other than those
        described in MessageDict and should add/modify keys in a backward
        compatible way.
        """
        raise NotImplementedError


class NLUPipeline:
    """Main NLU pipeline that manages components and their execution order.

    The pipeline is storage-agnostic: callers can pass either a filesystem path
    or a ModelStorage implementation to train/load. When a simple path is
    provided, the pipeline will ensure the directory exists before training.
    """

    def __init__(self, components: Optional[List[NLUComponent]] = None) -> None:
        """Initialize NLU pipeline with optional list of components."""
        self.components: List[NLUComponent] = components or []

    def add_component(self, component: NLUComponent) -> None:
        """Add a component to the pipeline."""
        self.components.append(component)

    def train(self, training_data: TrainingData, model_path: ModelPath) -> None:
        """Train all components in the pipeline.

        If model_path is a filesystem path, ensure the directory exists. If a
        ModelStorage is provided, the storage is passed through and components
        are expected to handle directory creation there.
        """
        # Ensure local directory exists when a path-like is given
        if isinstance(model_path, (str, os.PathLike)):
            Path(model_path).mkdir(parents=True, exist_ok=True)

        for component in self.components:
            component.train(training_data, model_path)

    def load(self, model_path: ModelPath) -> bool:
        """Load all components from model_path.

        Returns True only if all components successfully loaded.
        """
        for component in self.components:
            if not component.load(model_path):
                return False
        return True

    def process(self, message: MessageDict) -> MessageDict:
        """Process message through all components in sequence and return result."""
        current: MessageDict = message
        for component in self.components:
            current = component.process(current)
        return current