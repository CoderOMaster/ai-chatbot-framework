"""NLU Pipeline framework for orchestrating NLU components.

This module provides framework-agnostic abstractions for building
composable NLU processing pipelines. It is designed to be reusable
across training and inference microservices.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import os


class NLUComponent(ABC):
    """Abstract base class for NLU pipeline components.
    
    All NLU components must implement this interface to be compatible
    with the NLUPipeline orchestration framework.
    """

    @abstractmethod
    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the component with given training data and save to model_path.
        
        Args:
            training_data: List of training examples, each as a dictionary.
            model_path: Directory path where trained model artifacts should be saved.
            
        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def load(self, model_path: str) -> bool:
        """Load the component from given model path.
        
        Args:
            model_path: Directory path containing saved model artifacts.
            
        Returns:
            True if loading succeeded, False otherwise.
            
        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.
        
        Args:
            message: Input message dictionary to process.
            
        Returns:
            Processed message dictionary with component-specific enrichments.
            
        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass


class NLUPipeline:
    """Main NLU pipeline that manages components and their execution order.
    
    This class orchestrates a sequence of NLUComponent instances,
    coordinating their training and inference phases.
    """

    def __init__(self, components: Optional[List[NLUComponent]] = None) -> None:
        """Initialize NLU pipeline with optional list of components.
        
        Args:
            components: Optional list of NLUComponent instances to initialize with.
                       Defaults to empty list if not provided.
        """
        self.components: List[NLUComponent] = components or []

    def add_component(self, component: NLUComponent) -> None:
        """Add a component to the pipeline.
        
        Args:
            component: NLUComponent instance to add to the pipeline.
            
        Raises:
            TypeError: If component does not implement NLUComponent interface.
        """
        if not isinstance(component, NLUComponent):
            raise TypeError(
                f"Component must be an instance of NLUComponent, "
                f"got {type(component).__name__}"
            )
        self.components.append(component)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train all components in the pipeline.
        
        Creates the model_path directory if it does not exist, then
        sequentially trains each component in registration order.
        
        Args:
            training_data: List of training examples to use for all components.
            model_path: Directory path where all component models will be saved.
            
        Raises:
            OSError: If model_path directory cannot be created.
        """
        if not os.path.exists(model_path):
            os.makedirs(model_path)

        for component in self.components:
            component.train(training_data, model_path)

    def load(self, model_path: str) -> bool:
        """Load all components from model path.
        
        Sequentially loads each component in registration order.
        If any component fails to load, returns False immediately.
        
        Args:
            model_path: Directory path containing saved component models.
            
        Returns:
            True if all components loaded successfully, False if any failed.
        """
        for component in self.components:
            if not component.load(model_path):
                return False
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process message through all components in sequence.
        
        Each component receives the output of the previous component
        as input, allowing for composable processing pipelines.
        
        Args:
            message: Input message dictionary to process.
            
        Returns:
            Final processed message after all components have executed.
        """
        for component in self.components:
            message = component.process(message)
        return message