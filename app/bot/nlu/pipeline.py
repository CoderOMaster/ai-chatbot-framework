from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Pipeline execution modes."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class ComponentMetrics:
    """Metrics collected for a component execution."""
    component_name: str
    execution_time: float
    timestamp: datetime
    status: str = "success"
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "component_name": self.component_name,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "error": self.error,
        }


@dataclass
class PipelineMetrics:
    """Aggregated metrics for pipeline execution."""
    total_time: float
    component_metrics: List[ComponentMetrics] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert pipeline metrics to dictionary."""
        return {
            "total_time": self.total_time,
            "component_metrics": [m.to_dict() for m in self.component_metrics],
            "timestamp": self.timestamp.isoformat(),
        }


class NLUComponent(ABC):
    """Abstract base class for NLU pipeline components."""

    def __init__(self, name: str, parallelizable: bool = False):
        """Initialize component with name and parallelization capability.
        
        Args:
            name: Unique identifier for the component
            parallelizable: Whether component can run in parallel with others
        """
        self.name = name
        self.parallelizable = parallelizable
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        """Check if component is loaded."""
        return self._is_loaded

    @abstractmethod
    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the component with given training data
        and save to model_path.
        
        Args:
            training_data: List of training examples
            model_path: Path to save trained model
        """
        pass

    @abstractmethod
    def load(self, model_path: str) -> bool:
        """Load the component from given model path.
        
        Args:
            model_path: Path to load model from
            
        Returns:
            True if load successful, False otherwise
        """
        pass

    @abstractmethod
    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.
        
        Args:
            message: Input message to process
            
        Returns:
            Processed message with component output
        """
        pass

    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate component state and configuration.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.is_loaded:
            return False, f"Component '{self.name}' is not loaded"
        return True, None


class PipelineBuilder:
    """Builder pattern for constructing NLU pipelines."""

    def __init__(self, version: str = "1.0.0"):
        """Initialize pipeline builder.
        
        Args:
            version: Pipeline version identifier
        """
        self.components: List[NLUComponent] = []
        self.version = version
        self.execution_mode = ExecutionMode.SEQUENTIAL
        self.max_workers = 4

    def add_component(self, component: NLUComponent) -> "PipelineBuilder":
        """Add component to pipeline.
        
        Args:
            component: NLU component to add
            
        Returns:
            Self for method chaining
        """
        if not isinstance(component, NLUComponent):
            raise TypeError(f"Component must be instance of NLUComponent, got {type(component)}")
        self.components.append(component)
        return self

    def set_execution_mode(self, mode: ExecutionMode) -> "PipelineBuilder":
        """Set pipeline execution mode.
        
        Args:
            mode: Execution mode (sequential or parallel)
            
        Returns:
            Self for method chaining
        """
        self.execution_mode = mode
        return self

    def set_max_workers(self, max_workers: int) -> "PipelineBuilder":
        """Set maximum workers for parallel execution.
        
        Args:
            max_workers: Number of parallel workers
            
        Returns:
            Self for method chaining
        """
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.max_workers = max_workers
        return self

    def build(self) -> "NLUPipeline":
        """Build the NLU pipeline.
        
        Returns:
            Configured NLU pipeline instance
        """
        if not self.components:
            raise ValueError("Pipeline must have at least one component")
        
        pipeline = NLUPipeline(
            components=self.components,
            version=self.version,
            execution_mode=self.execution_mode,
            max_workers=self.max_workers,
        )
        return pipeline


class NLUPipeline:
    """Main NLU pipeline that manages components and their execution order."""

    def __init__(
        self,
        components: Optional[List[NLUComponent]] = None,
        version: str = "1.0.0",
        execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        max_workers: int = 4,
    ):
        """Initialize NLU pipeline with optional list of components.
        
        Args:
            components: List of NLU components
            version: Pipeline version identifier
            execution_mode: How to execute components (sequential or parallel)
            max_workers: Maximum workers for parallel execution
        """
        self.components = components or []
        self.version = version
        self.execution_mode = execution_mode
        self.max_workers = max_workers
        self._metrics_hooks: List[Callable[[ComponentMetrics], None]] = []
        self._last_metrics: Optional[PipelineMetrics] = None

    def add_component(self, component: NLUComponent) -> None:
        """Add a component to the pipeline.
        
        Args:
            component: NLU component to add
            
        Raises:
            TypeError: If component is not an NLUComponent instance
        """
        if not isinstance(component, NLUComponent):
            raise TypeError(f"Component must be instance of NLUComponent, got {type(component)}")
        self.components.append(component)

    def register_metrics_hook(self, hook: Callable[[ComponentMetrics], None]) -> None:
        """Register a callback for component metrics collection.
        
        Args:
            hook: Callable that receives ComponentMetrics
        """
        self._metrics_hooks.append(hook)

    def validate_components(self) -> Tuple[bool, List[str]]:
        """Validate all components in the pipeline.
        
        Returns:
            Tuple of (all_valid, list_of_errors)
        """
        errors = []
        for component in self.components:
            is_valid, error_msg = component.validate()
            if not is_valid:
                errors.append(error_msg)
        
        return len(errors) == 0, errors

    def _collect_metrics(self, metrics: ComponentMetrics) -> None:
        """Collect metrics from component execution.
        
        Args:
            metrics: Component metrics to collect
        """
        for hook in self._metrics_hooks:
            try:
                hook(metrics)
            except Exception as e:
                logger.warning(f"Error in metrics hook: {e}")

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train all components in the pipeline.
        
        Args:
            training_data: List of training examples
            model_path: Path to save trained models
        """
        if not os.path.exists(model_path):
            os.makedirs(model_path)

        for component in self.components:
            start_time = time.time()
            try:
                component.train(training_data, model_path)
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="success",
                )
                self._collect_metrics(metrics)
                logger.info(f"Trained component '{component.name}' in {execution_time:.2f}s")
            except Exception as e:
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="failed",
                    error=str(e),
                )
                self._collect_metrics(metrics)
                logger.error(f"Failed to train component '{component.name}': {e}")
                raise

    def load(self, model_path: str) -> bool:
        """Load all components from model path.
        
        Args:
            model_path: Path to load models from
            
        Returns:
            True if all components loaded successfully
        """
        for component in self.components:
            start_time = time.time()
            try:
                success = component.load(model_path)
                execution_time = time.time() - start_time
                
                if success:
                    component._is_loaded = True
                    metrics = ComponentMetrics(
                        component_name=component.name,
                        execution_time=execution_time,
                        timestamp=datetime.now(),
                        status="success",
                    )
                else:
                    metrics = ComponentMetrics(
                        component_name=component.name,
                        execution_time=execution_time,
                        timestamp=datetime.now(),
                        status="failed",
                        error="Load returned False",
                    )
                
                self._collect_metrics(metrics)
                
                if not success:
                    logger.error(f"Failed to load component '{component.name}'")
                    return False
                    
                logger.info(f"Loaded component '{component.name}' in {execution_time:.2f}s")
            except Exception as e:
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="failed",
                    error=str(e),
                )
                self._collect_metrics(metrics)
                logger.error(f"Error loading component '{component.name}': {e}")
                return False
        
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process message through all components.
        
        Execution mode (sequential or parallel) is determined by pipeline configuration.
        
        Args:
            message: Input message to process
            
        Returns:
            Processed message with all component outputs
        """
        is_valid, errors = self.validate_components()
        if not is_valid:
            raise RuntimeError(f"Pipeline validation failed: {errors}")

        pipeline_start = time.time()
        component_metrics_list = []

        if self.execution_mode == ExecutionMode.PARALLEL:
            message = self._process_parallel(message, component_metrics_list)
        else:
            message = self._process_sequential(message, component_metrics_list)

        total_time = time.time() - pipeline_start
        self._last_metrics = PipelineMetrics(
            total_time=total_time,
            component_metrics=component_metrics_list,
        )

        return message

    def _process_sequential(
        self,
        message: Dict[str, Any],
        metrics_list: List[ComponentMetrics],
    ) -> Dict[str, Any]:
        """Process message through components sequentially.
        
        Args:
            message: Input message
            metrics_list: List to collect metrics
            
        Returns:
            Processed message
        """
        for component in self.components:
            start_time = time.time()
            try:
                message = component.process(message)
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="success",
                )
                metrics_list.append(metrics)
                self._collect_metrics(metrics)
            except Exception as e:
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="failed",
                    error=str(e),
                )
                metrics_list.append(metrics)
                self._collect_metrics(metrics)
                logger.error(f"Error processing with component '{component.name}': {e}")
                raise

        return message

    def _process_parallel(
        self,
        message: Dict[str, Any],
        metrics_list: List[ComponentMetrics],
    ) -> Dict[str, Any]:
        """Process message through parallelizable components concurrently.
        
        Components marked as parallelizable are executed in parallel,
        while non-parallelizable components are executed sequentially.
        
        Args:
            message: Input message
            metrics_list: List to collect metrics
            
        Returns:
            Processed message
        """
        # Separate parallelizable and sequential components
        parallel_components = [c for c in self.components if c.parallelizable]
        sequential_components = [c for c in self.components if not c.parallelizable]

        # Process sequential components first
        for component in sequential_components:
            start_time = time.time()
            try:
                message = component.process(message)
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="success",
                )
                metrics_list.append(metrics)
                self._collect_metrics(metrics)
            except Exception as e:
                execution_time = time.time() - start_time
                metrics = ComponentMetrics(
                    component_name=component.name,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    status="failed",
                    error=str(e),
                )
                metrics_list.append(metrics)
                self._collect_metrics(metrics)
                logger.error(f"Error processing with component '{component.name}': {e}")
                raise

        # Process parallelizable components in parallel
        if parallel_components:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._execute_component, component, message): component
                    for component in parallel_components
                }

                for future in as_completed(futures):
                    component = futures[future]
                    try:
                        result, execution_time = future.result()
                        message.update(result)
                        metrics = ComponentMetrics(
                            component_name=component.name,
                            execution_time=execution_time,
                            timestamp=datetime.now(),
                            status="success",
                        )
                        metrics_list.append(metrics)
                        self._collect_metrics(metrics)
                    except Exception as e:
                        metrics = ComponentMetrics(
                            component_name=component.name,
                            execution_time=0.0,
                            timestamp=datetime.now(),
                            status="failed",
                            error=str(e),
                        )
                        metrics_list.append(metrics)
                        self._collect_metrics(metrics)
                        logger.error(f"Error in parallel component '{component.name}': {e}")
                        raise

        return message

    @staticmethod
    def _execute_component(
        component: NLUComponent,
        message: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], float]:
        """Execute a single component and measure execution time.
        
        Args:
            component: Component to execute
            message: Input message
            
        Returns:
            Tuple of (component_output, execution_time)
        """
        start_time = time.time()
        result = component.process(message)
        execution_time = time.time() - start_time
        return result, execution_time

    def get_last_metrics(self) -> Optional[PipelineMetrics]:
        """Get metrics from last pipeline execution.
        
        Returns:
            PipelineMetrics from last execution or None if not executed
        """
        return self._last_metrics

    @classmethod
    def builder(cls, version: str = "1.0.0") -> PipelineBuilder:
        """Create a pipeline builder.
        
        Args:
            version: Pipeline version identifier
            
        Returns:
            PipelineBuilder instance
        """
        return PipelineBuilder(version=version)