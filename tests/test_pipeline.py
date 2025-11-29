from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.bot.nlu.pipeline import (
    ModelStorage,
    MessagePayload,
    NLUPipeline,
    NLUComponent,
    TrainingDataset,
    _resolve_model_path,
)


class RecordingComponent(NLUComponent):
    """Simple component that records invocation parameters for assertions."""

    def __init__(self) -> None:
        self.train_calls: List[Dict[str, Any]] = []
        self.load_calls: List[str] = []
        self.process_calls: List[MessagePayload] = []
        self.load_result: bool = True
        self.process_return_message: MessagePayload | None = None

    def train(self, training_data: TrainingDataset, model_path: str) -> None:  # type: ignore[override]
        self.train_calls.append({"training_data": training_data, "model_path": model_path})

    def load(self, model_path: str) -> bool:  # type: ignore[override]
        self.load_calls.append(model_path)
        return self.load_result

    def process(self, message: MessagePayload) -> MessagePayload:  # type: ignore[override]
        self.process_calls.append(dict(message))
        if self.process_return_message is not None:
            return self.process_return_message
        output = dict(message)
        output.setdefault("history", []).append("recorded")
        return output


class MutatingComponent(NLUComponent):
    """Component that merges a provided update payload into the message."""

    def __init__(self, update: Dict[str, Any]) -> None:
        self.update = update
        self.process_calls: List[MessagePayload] = []

    def train(self, training_data: TrainingDataset, model_path: str) -> None:  # type: ignore[override]
        pass

    def load(self, model_path: str) -> bool:  # type: ignore[override]
        return True

    def process(self, message: MessagePayload) -> MessagePayload:  # type: ignore[override]
        self.process_calls.append(dict(message))
        output = dict(message)
        output.update(self.update)
        return output


class DummyStorage(ModelStorage):
    """Minimal ModelStorage used to test _resolve_model_path and storage-aware flows."""

    def __init__(self, path: str) -> None:
        self._path = path
        self.get_model_path_calls: List[None] = []

    def get_model_path(self) -> str:  # type: ignore[override]
        self.get_model_path_calls.append(None)
        return self._path


@pytest.fixture
def training_examples() -> TrainingDataset:
    """Provide a minimal training dataset for pipeline operations."""
    return [{"text": "hello", "intent": "greet"}]


@pytest.fixture
def sample_message() -> MessagePayload:
    """Generate a sample message payload to feed through the pipeline."""
    return {"text": "hi there", "metadata": {}}


def test_resolve_model_path_with_string_input() -> None:
    """_resolve_model_path should return the original string when provided a str path."""
    path = "./models/nlu"
    assert _resolve_model_path(path) == path


def test_resolve_model_path_with_pathlike_input(tmp_path: Path) -> None:
    """_resolve_model_path should accept os.PathLike inputs and return strings."""
    pathlike = tmp_path / "persistent"
    resolved = _resolve_model_path(pathlike)
    assert isinstance(resolved, str)
    assert resolved == os.fspath(pathlike)


def test_resolve_model_path_with_model_storage() -> None:
    """_resolve_model_path should delegate to ModelStorage.get_model_path when given a storage object."""
    storage = DummyStorage("/tmp/state")
    resolved = _resolve_model_path(storage)
    assert resolved == "/tmp/state"
    assert storage.get_model_path_calls == [None]


def test_train_creates_directory_for_string_storage(
    tmp_path: Path, training_examples: TrainingDataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Training should create filesystem directories when storage is a path string."""
    pipeline = NLUPipeline([RecordingComponent()])
    records: Dict[str, Any] = {}

    def fake_makedirs(path: str, exist_ok: bool) -> None:
        records["path"] = path
        records["exist_ok"] = exist_ok

    monkeypatch.setattr(os, "makedirs", fake_makedirs)
    model_dir = tmp_path / "model"

    pipeline.train(training_examples, str(model_dir))

    assert records["path"] == str(model_dir)
    assert records["exist_ok"] is True
    recorded_component = pipeline.components[0]
    assert isinstance(recorded_component, RecordingComponent)
    assert recorded_component.train_calls
    assert recorded_component.train_calls[0]["model_path"] == str(model_dir)
    assert recorded_component.train_calls[0]["training_data"] == training_examples


def test_train_with_model_storage_skips_directory_creation(
    tmp_path: Path, training_examples: TrainingDataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a ModelStorage is supplied, the pipeline should rely on the storage instead of making directories."""
    pipeline = NLUPipeline([RecordingComponent()])
    storage = DummyStorage(str(tmp_path / "state"))

    def bogus_makedirs(*_: Any, **__: Any) -> None:
        raise AssertionError("os.makedirs should not be called when using ModelStorage")

    monkeypatch.setattr(os, "makedirs", bogus_makedirs)

    pipeline.train(training_examples, storage)

    recorded_component = pipeline.components[0]
    assert isinstance(recorded_component, RecordingComponent)
    assert recorded_component.train_calls
    assert recorded_component.train_calls[0]["model_path"] == str(tmp_path / "state")


def test_load_returns_true_for_all_components(tmp_path: Path) -> None:
    """NLUPipeline.load should succeed when every component loads successfully."""
    component_a = RecordingComponent()
    component_b = RecordingComponent()
    pipeline = NLUPipeline([component_a, component_b])
    result = pipeline.load(str(tmp_path / "exists"))
    assert result is True
    assert component_a.load_calls == [str(tmp_path / "exists")]
    assert component_b.load_calls == [str(tmp_path / "exists")]


def test_load_short_circuits_on_failure(tmp_path: Path) -> None:
    """If any component fails to load, the pipeline should stop and return False."""
    component_a = RecordingComponent()
    component_b = RecordingComponent()
    component_a.load_result = False

    pipeline = NLUPipeline([component_a, component_b])
    result = pipeline.load(str(tmp_path / "missing"))

    assert result is False
    assert component_a.load_calls == [str(tmp_path / "missing")]
    assert component_b.load_calls == []


def test_process_applies_components_in_sequence(sample_message: MessagePayload) -> None:
    """MessagePayload should flow through each component in turn, accumulating their modifications."""
    pipeline = NLUPipeline(
        [
            MutatingComponent({"stage": "first"}),
            MutatingComponent({"second_stage": True}),
        ]
    )
    result = pipeline.process(sample_message)

    assert result["stage"] == "first"
    assert result["second_stage"] is True
    assert pipeline.components[0].process_calls[0]["text"] == sample_message["text"]
    assert pipeline.components[1].process_calls[0]["stage"] == "first"


def test_process_preserves_original_payload(sample_message: MessagePayload) -> None:
    """Process should avoid mutating the input payload and return a new message dict."""
    pipeline = NLUPipeline([RecordingComponent()])
    copy_before = dict(sample_message)

    pipeline.process(sample_message)

    assert sample_message == copy_before
    assert pipeline.components[0].process_calls


def test_train_with_no_components_still_prepares_path(
    tmp_path: Path, training_examples: TrainingDataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even without components, training should create the storage directory for filesystem paths."""
    pipeline = NLUPipeline()
    called: List[Dict[str, Any]] = []

    def fake_makedirs(path: str, exist_ok: bool) -> None:
        called.append({"path": path, "exist_ok": exist_ok})

    monkeypatch.setattr(os, "makedirs", fake_makedirs)
    pipeline.train(training_examples, tmp_path / "empty")

    assert called and called[0]["exist_ok"] is True