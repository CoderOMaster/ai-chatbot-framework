"""Core NLU pipeline interfaces and orchestration.

This module defines the abstract base classes and orchestrator for the NLU pipeline,
providing the foundation for all NLU components and their execution.
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class NLUComponent(ABC):
    """Abstract base class for NLU pipeline components.
    
    All NLU components must inherit from this class and implement the required
    abstract methods for training, loading, and processing messages.
    """

    @abstractmethod
    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the component with given training data and save to model_path.
        
        Args:
            training_data: List of training examples, each as a dictionary.
            model_path: Path where the trained model should be saved.
            
        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def load(self, model_path: str) -> bool:
        """Load the component from given model path.
        
        Args:
            model_path: Path to load the model from.
            
        Returns:
            True if loading was successful, False otherwise.
            
        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.
        
        Args:
            message: Input message as a dictionary.
            
        Returns:
            Processed message with extracted information.
            
        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        pass


class NLUPipeline:
    """Main NLU pipeline that manages components and their execution order.
    
    The pipeline orchestrates multiple NLU components, executing them sequentially
    during training and inference phases. Supports both synchronous and async operations.
    """

    def __init__(self, components: Optional[List[NLUComponent]] = None) -> None:
        """Initialize NLU pipeline with optional list of components.
        
        Args:
            components: Optional list of NLUComponent instances to initialize with.
        """
        self.components: List[NLUComponent] = components or []

    def add_component(self, component: NLUComponent) -> None:
        """Add a component to the pipeline.
        
        Args:
            component: NLUComponent instance to add to the pipeline.
        """
        self.components.append(component)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train all components in the pipeline.
        
        Creates the model directory if it doesn't exist, then trains each
        component sequentially with the provided training data.
        
        Args:
            training_data: List of training examples.
            model_path: Directory path where models will be saved.
        """
        if not os.path.exists(model_path):
            os.makedirs(model_path)

        for component in self.components:
            component.train(training_data, model_path)

    def load(self, model_path: str) -> bool:
        """Load all components from model path.
        
        Loads each component sequentially. Returns False if any component
        fails to load.
        
        Args:
            model_path: Directory path to load models from.
            
        Returns:
            True if all components loaded successfully, False otherwise.
        """
        for component in self.components:
            if not component.load(model_path):
                return False
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process message through all components in sequence.
        
        Each component receives the output of the previous component,
        allowing for chained processing and information enrichment.
        
        Args:
            message: Input message to process.
            
        Returns:
            Processed message with all component outputs applied.
        """
        for component in self.components:
            message = component.process(message)
        return message