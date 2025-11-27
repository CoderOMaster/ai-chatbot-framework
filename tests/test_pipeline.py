import os
import time
from datetime import datetime
import pytest

from app.bot.nlu.pipeline import (
    ExecutionMode,
    ComponentMetrics,
    PipelineMetrics,
    NLUComponent,
    PipelineBuilder,
    NLUPipeline,
)


class DummyComponent(NLUComponent):
    def __init__(
        self,
        name,
        parallelizable=False,
        train_raise=False,
        load_return=True,
        process_raise=False,
        process_result=None,
        load_raise=False,
    ):
        super().__init__(name=name, parallelizable=parallelizable)
        self.train_called = False
        self.train_raise = train_raise
        self.load_return = load_return
        self.load_raise = load_raise
        self.process_raise = process_raise
        self.process_result = process_result or {f"{name}_out": True}

    def train(self, training_data, model_path):
        self.train_called = True
        if self.train_raise:
            raise RuntimeError("train failure")

    def load(self, model_path):
        if self.load_raise:
            raise RuntimeError("load failure")
        return self.load_return

    def process(self, message):
        if self.process_raise:
            raise RuntimeError("process failure")
        # return a shallow copy of updates
        return dict(self.process_result)


def test_execution_mode_enum_values() -> None:
    """Ensure ExecutionMode enum contains expected values."""
    assert ExecutionMode.SEQUENTIAL.value == "sequential"
    assert ExecutionMode.PARALLEL.value == "parallel"


def test_component_metrics_to_dict() -> None:
    """ComponentMetrics.to_dict returns properly formatted dict including ISO timestamp."""
    cm = ComponentMetrics(component_name="c", execution_time=0.1, timestamp=datetime(2020, 1, 1), status="success")
    d = cm.to_dict()
    assert d["component_name"] == "c"
    assert d["execution_time"] == 0.1
    assert d["timestamp"] == "2020-01-01T00:00:00"
    assert d["status"] == "success"
    assert d["error"] is None


def test_pipeline_metrics_to_dict() -> None:
    """PipelineMetrics.to_dict serializes nested component metrics."""
    cm = ComponentMetrics(component_name="c", execution_time=0.2, timestamp=datetime(2020, 1, 1), status="success")
    pm = PipelineMetrics(total_time=1.2, component_metrics=[cm], timestamp=datetime(2020, 1, 2))
    d = pm.to_dict()
    assert d["total_time"] == 1.2
    assert isinstance(d["component_metrics"], list) and d["component_metrics"][0]["component_name"] == "c"
    assert d["timestamp"] == "2020-01-02T00:00:00"


def test_pipeline_builder_add_component_type_error() -> None:
    """Adding non-NLUComponent to builder should raise TypeError."""
    pb = PipelineBuilder()
    with pytest.raises(TypeError):
        pb.add_component(object())


def test_pipeline_builder_set_max_workers_validation() -> None:
    """Setting max_workers less than 1 should raise ValueError."""
    pb = PipelineBuilder()
    with pytest.raises(ValueError):
        pb.set_max_workers(0)


def test_pipeline_builder_build_without_components_raises() -> None:
    """Building a pipeline without components raises ValueError."""
    pb = PipelineBuilder()
    with pytest.raises(ValueError):
        pb.build()


def test_pipeline_builder_build_success() -> None:
    """Builder builds a NLUPipeline when components are present and respects version."""
    pb = PipelineBuilder(version="2.0.0")
    comp = DummyComponent("c1")
    pb.add_component(comp)
    pb.set_execution_mode(ExecutionMode.PARALLEL)
    pb.set_max_workers(2)
    pipeline = pb.build()
    assert isinstance(pipeline, NLUPipeline)
    assert pipeline.version == "2.0.0"
    assert pipeline.execution_mode == ExecutionMode.PARALLEL
    assert pipeline.max_workers == 2


def test_pipeline_add_component_type_error() -> None:
    """Adding non-NLUComponent to NLUPipeline should raise TypeError."""
    p = NLUPipeline()
    with pytest.raises(TypeError):
        p.add_component(object())


def test_validate_components_unloaded_and_loaded() -> None:
    """validate_components returns errors for unloaded components and passes for loaded ones."""
    c1 = DummyComponent("c1")
    c2 = DummyComponent("c2")
    p = NLUPipeline(components=[c1, c2])

    all_valid, errors = p.validate_components()
    assert not all_valid
    assert any("not loaded" in e for e in errors)

    # mark loaded
    c1._is_loaded = True
    c2._is_loaded = True
    all_valid, errors = p.validate_components()
    assert all_valid and errors == []


def test_train_calls_component_train_and_metrics_hook_on_success(tmp_path) -> None:
    """Training pipeline should call component.train and invoke metrics hooks on success."""
    model_path = tmp_path / "model_dir"
    comp = DummyComponent("c_train")
    p = NLUPipeline(components=[comp])

    called_hooks = []

    def hook(metrics):
        called_hooks.append(metrics)

    p.register_metrics_hook(hook)
    p.train(training_data=[{"text": "hi"}], model_path=str(model_path))

    assert comp.train_called
    assert len(called_hooks) == 1
    assert called_hooks[0].component_name == "c_train"
    assert called_hooks[0].status == "success"


def test_train_component_raises_collects_metrics_and_raises(tmp_path) -> None:
    """If a component.train raises, pipeline.train collects failed metrics and re-raises the exception."""
    model_path = tmp_path / "model_dir2"
    comp = DummyComponent("c_train_fail", train_raise=True)
    p = NLUPipeline(components=[comp])

    called_hooks = []

    def hook(metrics):
        called_hooks.append(metrics)

    p.register_metrics_hook(hook)
    with pytest.raises(RuntimeError):
        p.train(training_data=[{"text": "x"}], model_path=str(model_path))

    assert len(called_hooks) == 1
    assert called_hooks[0].status == "failed"
    assert "train failure" in called_hooks[0].error


def test_load_all_components_success_and_metrics_hook(tmp_path) -> None:
    """Loading components that return True should mark them as loaded and call metrics hook."""
    model_path = tmp_path / "load_model"
    comp = DummyComponent("c_load", load_return=True)
    p = NLUPipeline(components=[comp])

    hooks = []

    def hook(metrics):
        hooks.append(metrics)

    p.register_metrics_hook(hook)
    success = p.load(str(model_path))
    assert success is True
    assert comp.is_loaded is True
    assert len(hooks) == 1
    assert hooks[0].status == "success"


def test_load_returns_false_collects_metrics(tmp_path) -> None:
    """If a component.load returns False the pipeline.load returns False and collects metrics."""
    model_path = tmp_path / "load_model2"
    comp = DummyComponent("c_load_false", load_return=False)
    p = NLUPipeline(components=[comp])

    hooks = []

    def hook(metrics):
        hooks.append(metrics)

    p.register_metrics_hook(hook)
    success = p.load(str(model_path))
    assert success is False
    assert len(hooks) == 1
    assert hooks[0].status == "failed"
    assert hooks[0].error == "Load returned False"


def test_load_raises_exception_returns_false(tmp_path) -> None:
    """If component.load raises exception pipeline.load returns False and collects failed metric."""
    model_path = tmp_path / "load_model3"
    comp = DummyComponent("c_load_exc", load_raise=True)
    p = NLUPipeline(components=[comp])

    hooks = []

    def hook(metrics):
        hooks.append(metrics)

    p.register_metrics_hook(hook)
    success = p.load(str(model_path))
    assert success is False
    assert len(hooks) == 1
    assert hooks[0].status == "failed"
    assert "load failure" in (hooks[0].error or "")


def test_process_validation_fails_raises() -> None:
    """If any component is not loaded, process should raise RuntimeError due to validation failure."""
    c = DummyComponent("c_proc")
    p = NLUPipeline(components=[c])
    with pytest.raises(RuntimeError):
        p.process({})


def test_process_sequential_success_and_metrics_and_get_last_metrics() -> None:
    """Sequential processing should apply components in order, collect metrics and set last metrics."""
    c1 = DummyComponent("c1")
    c2 = DummyComponent("c2")
    # mark loaded so validation passes
    c1._is_loaded = True
    c2._is_loaded = True

    p = NLUPipeline(components=[c1, c2], execution_mode=ExecutionMode.SEQUENTIAL)

    called = []

    def hook(metrics):
        called.append(metrics)

    p.register_metrics_hook(hook)
    out = p.process({"initial": True})
    # Each component returns dict with their output
    assert "c1_out" in out and "c2_out" in out
    assert len(called) == 2
    last = p.get_last_metrics()
    assert last is not None and isinstance(last.total_time, float)
    assert len(last.component_metrics) == 2


def test_process_sequential_component_raises_collects_metrics_and_raises() -> None:
    """If a component.process raises in sequential mode, pipeline.process should collect failed metrics and re-raise."""
    c1 = DummyComponent("c_ok")
    c2 = DummyComponent("c_bad", process_raise=True)
    c1._is_loaded = True
    c2._is_loaded = True
    p = NLUPipeline(components=[c1, c2], execution_mode=ExecutionMode.SEQUENTIAL)

    hooks = []

    def hook(metrics):
        hooks.append(metrics)

    p.register_metrics_hook(hook)
    with pytest.raises(RuntimeError):
        p.process({})

    # ensure two metrics were collected: one success and one failed
    assert len(hooks) == 2
    assert hooks[0].status == "success"
    assert hooks[1].status == "failed"
    assert "process failure" in (hooks[1].error or "")


def test_process_parallel_execution_merges_results_and_metrics() -> None:
    """Parallel execution should run parallelizable components concurrently and merge their outputs into the message."""
    # sequential component modifies message first
    seq = DummyComponent("seq", parallelizable=False, process_result={"base": 1})
    p1 = DummyComponent("p1", parallelizable=True, process_result={"p1": 10})
    p2 = DummyComponent("p2", parallelizable=True, process_result={"p2": 20})

    seq._is_loaded = True
    p1._is_loaded = True
    p2._is_loaded = True

    # add small sleeps to simulate work
    original_process_p1 = p1.process

    def slow_p1(msg):
        time.sleep(0.1)
        return original_process_p1(msg)

    p1.process = slow_p1

    original_process_p2 = p2.process

    def slow_p2(msg):
        time.sleep(0.1)
        return original_process_p2(msg)

    p2.process = slow_p2

    pipeline = NLUPipeline(components=[seq, p1, p2], execution_mode=ExecutionMode.PARALLEL, max_workers=2)

    metrics = []

    def hook(m):
        metrics.append(m)

    pipeline.register_metrics_hook(hook)
    out = pipeline.process({})

    # sequential component output should be present
    assert out.get("base") == 1
    # parallel components outputs should be merged
    assert out.get("p1") == 10
    assert out.get("p2") == 20
    # metrics should include three entries
    assert len(metrics) == 3
    statuses = [m.status for m in metrics]
    assert all(s == "success" for s in statuses)