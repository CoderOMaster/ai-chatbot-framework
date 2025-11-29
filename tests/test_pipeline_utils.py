import sys
import types
from types import SimpleNamespace
from typing import Any, Mapping

# Stub the heavy NLU components before importing pipeline utilities to prevent external dependencies


class DummySpacyFeaturizer:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name


class DummySklearnIntentClassifier:
    pass


class DummyCRFEntityExtractor:
    pass


class DummySynonymReplacer:
    def __init__(self, synonyms: Mapping[str, str]) -> None:
        self.synonyms = dict(synonyms)


class DummyZeroShotNLUOpenAI:
    def __init__(self, *, intents: list[str], entities: list[str], **kwargs: Any) -> None:
        self.intents = intents
        self.entities = entities
        self.kwargs = kwargs


def _install_stub_modules() -> None:
    entity_module = types.ModuleType("app.bot.nlu.entity_extractors")
    entity_module.CRFEntityExtractor = DummyCRFEntityExtractor
    entity_module.SynonymReplacer = DummySynonymReplacer
    sys.modules["app.bot.nlu.entity_extractors"] = entity_module

    featurizer_module = types.ModuleType("app.bot.nlu.featurizers")
    featurizer_module.SpacyFeaturizer = DummySpacyFeaturizer
    sys.modules["app.bot.nlu.featurizers"] = featurizer_module

    classifiers_module = types.ModuleType("app.bot.nlu.intent_classifiers")
    classifiers_module.SklearnIntentClassifier = DummySklearnIntentClassifier
    sys.modules["app.bot.nlu.intent_classifiers"] = classifiers_module

    llm_module = types.ModuleType("app.bot.nlu.llm")
    llm_module.ZeroShotNLUOpenAI = DummyZeroShotNLUOpenAI
    sys.modules["app.bot.nlu.llm"] = llm_module


_install_stub_modules()

import pytest
from unittest.mock import AsyncMock

from app.admin.bots.schemas import PipelineType
from app.bot.nlu import pipeline_utils


class DummyIntent:
    def __init__(self, intent_id: str, training_data: list[dict[str, Any]], parameters: list[SimpleNamespace]) -> None:
        self.intentId = intent_id
        self.trainingData = training_data
        self.parameters = parameters


class DummyIntentRepository:
    def __init__(self, intents: list[DummyIntent]) -> None:
        self._intents = intents

    async def list_intents(self) -> list[DummyIntent]:
        return self._intents


class DummyEntityRepository:
    def __init__(self, synonyms: Mapping[str, str]) -> None:
        self._synonyms = synonyms

    async def list_synonyms(self) -> Mapping[str, str]:
        return self._synonyms


class DummyBotRepository:
    def __init__(self, config: SimpleNamespace) -> None:
        self._config = config

    async def get_nlu_config(self, bot_name: str) -> SimpleNamespace:  # pragma: no cover - simple passthrough
        return self._config


@pytest.mark.asyncio
async def test_training_worker_entrypoint_invokes_train(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_train = AsyncMock()
    monkeypatch.setattr(pipeline_utils, "train_pipeline", mocked_train)

    await pipeline_utils.training_worker_entrypoint(
        intent_repository=SimpleNamespace(),
        entity_repository=SimpleNamespace(),
        bot_repository=SimpleNamespace(),
        models_dir="/tmp",
        spacy_model="en_core",
        bot_name="example",
    )

    mocked_train.assert_awaited_once()


@pytest.mark.asyncio
async def test_train_pipeline_raises_when_no_intents(tmp_path) -> None:
    repo = DummyIntentRepository([])
    entity_repo = DummyEntityRepository({})
    bot_repo = DummyBotRepository(SimpleNamespace(pipeline_type=PipelineType.ML, llm_settings=None))

    with pytest.raises(ValueError, match="No intents found for training"):
        await pipeline_utils.train_pipeline(
            intent_repository=repo,
            entity_repository=entity_repo,
            bot_repository=bot_repo,
            models_dir=str(tmp_path / "models"),
            spacy_model="en_core",
            bot_name="default",
        )


@pytest.mark.asyncio
async def test_train_pipeline_trains_with_filtered_examples(tmp_path, monkeypatch) -> None:
    intents = [
        DummyIntent(
            intent_id="greet",
            training_data=[
                {"text": "hello"},
                {"text": "   "},
                {"metadata": "no text"},
            ],
            parameters=[SimpleNamespace(name="location")],
        )
    ]
    repo = DummyIntentRepository(intents)
    entity_repo = DummyEntityRepository({"color": "blue"})
    bot_repo = DummyBotRepository(SimpleNamespace(pipeline_type=PipelineType.ML, llm_settings=None))

    trained_pipeline: list[tuple[list[dict[str, Any]], str]] = []

    class FakePipeline:
        def train(self, training_data: list[dict[str, Any]], model_dir: str) -> None:
            trained_pipeline.append((training_data, model_dir))

    captured: dict[str, Any] = {}

    def fake_builder(**kwargs: Any) -> FakePipeline:
        captured.update(kwargs)
        return FakePipeline()

    monkeypatch.setattr(pipeline_utils, "_build_pipeline_from_configuration", fake_builder)

    models_dir = str(tmp_path / "models")
    await pipeline_utils.train_pipeline(
        intent_repository=repo,
        entity_repository=entity_repo,
        bot_repository=bot_repo,
        models_dir=models_dir,
        spacy_model="en_core",
        bot_name="default",
    )

    assert trained_pipeline, "Pipeline.train should be invoked"
    training_data, trained_dir = trained_pipeline[0]
    assert trained_dir == models_dir
    assert len(training_data) == 1
    assert training_data[0]["intent"] == "greet"
    assert training_data[0]["text"] == "hello"
    assert captured["synonyms"] == {"color": "blue"}
    assert captured["intent_ids"] == ["greet"]
    assert captured["entity_ids"] == ["location"]
    assert (tmp_path / "models").exists()


@pytest.mark.asyncio
async def test_get_pipeline_zero_shot_requires_kwargs() -> None:
    with pytest.raises(ValueError, match="zero_shot_kwargs must be provided"):
        await pipeline_utils.get_pipeline(
            pipeline_type=PipelineType.ZERO_SHOT,
            spacy_model="en_core",
            zero_shot_intents=["greet"],
            zero_shot_entities=["location"],
        )


@pytest.mark.asyncio
async def test_get_pipeline_zero_shot_builds_pipeline(monkeypatch) -> None:
    created = {}

    def fake_zero_shot(*, intents, entities, synonyms, **kwargs: Any) -> object:
        created["intents"] = intents
        created["entities"] = entities
        created["synonyms"] = synonyms
        created.update(kwargs)
        return object()

    monkeypatch.setattr(pipeline_utils, "create_zero_shot_pipeline", fake_zero_shot)

    result = await pipeline_utils.get_pipeline(
        pipeline_type=PipelineType.ZERO_SHOT,
        spacy_model="unused",
        synonyms={"a": "b"},
        zero_shot_intents=["greet"],
        zero_shot_entities=["location"],
        zero_shot_kwargs={"llm_setting": "value"},
    )

    assert list(created["intents"]) == ["greet"]
    assert list(created["entities"]) == ["location"]
    assert created["synonyms"] == {"a": "b"}
    assert created["llm_setting"] == "value"
    assert result is not None


@pytest.mark.asyncio
async def test_get_pipeline_ml_delegates(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_ml_pipeline(*, spacy_model: str, synonyms: Mapping[str, str]) -> object:
        captured["spacy_model"] = spacy_model
        captured["synonyms"] = synonyms
        return object()

    monkeypatch.setattr(pipeline_utils, "create_ml_pipeline", fake_ml_pipeline)

    pipeline = await pipeline_utils.get_pipeline(
        pipeline_type=PipelineType.ML,
        spacy_model="en_core",
        synonyms={"foo": "bar"},
    )

    assert captured["spacy_model"] == "en_core"
    assert captured["synonyms"] == {"foo": "bar"}
    assert pipeline is not None


def test_create_ml_pipeline_contains_components() -> None:
    pipeline = pipeline_utils.create_ml_pipeline(spacy_model="en_core", synonyms={"test": "value"})

    assert pipeline.components, "Pipeline should contain components"
    assert isinstance(pipeline.components[0], DummySpacyFeaturizer)
    assert pipeline.components[0].model_name == "en_core"
    assert isinstance(pipeline.components[-1], DummySynonymReplacer)
    assert pipeline.components[-1].synonyms == {"test": "value"}


def test_create_zero_shot_pipeline_adds_llm_component() -> None:
    pipeline = pipeline_utils.create_zero_shot_pipeline(
        intents=["hello"],
        entities=["place"],
        synonyms={"test": "value"},
        model_name="stub",
    )

    assert isinstance(pipeline.components[0], DummyZeroShotNLUOpenAI)
    assert pipeline.components[0].intents == ["hello"]
    assert pipeline.components[0].entities == ["place"]
    assert pipeline.components[0].kwargs["model_name"] == "stub"
    assert isinstance(pipeline.components[-1], DummySynonymReplacer)


def test_ensure_directory_exists_creates_path(tmp_path) -> None:
    target = tmp_path / "models"
    pipeline_utils._ensure_directory_exists(str(target))
    assert target.exists()


def test_prepare_training_examples_filters_empty_text() -> None:
    intents = [
        DummyIntent(
            intent_id="test",
            training_data=[
                {"text": "valid"},
                {"text": "   "},
                {},
            ],
            parameters=[],
        )
    ]

    training_examples = pipeline_utils._prepare_training_examples(intents)
    assert len(training_examples) == 1
    assert training_examples[0]["intent"] == "test"
    assert training_examples[0]["text"] == "valid"


def test_extract_zero_shot_metadata_returns_collections() -> None:
    intents = [
        DummyIntent(
            intent_id="order",
            training_data=[],
            parameters=[SimpleNamespace(name="item"), SimpleNamespace(name="size")],
        ),
        DummyIntent(
            intent_id="cancel",
            training_data=[],
            parameters=[],
        ),
    ]

    intent_ids, entity_ids = pipeline_utils._extract_zero_shot_metadata(intents)
    assert intent_ids == ["order", "cancel"]
    assert entity_ids == ["item", "size"]


def test_build_pipeline_zero_shot_without_llm_raises() -> None:
    config = SimpleNamespace(pipeline_type=PipelineType.ZERO_SHOT, llm_settings=None)

    with pytest.raises(ValueError, match="LLM settings must be provided"):
        pipeline_utils._build_pipeline_from_configuration(
            config=config,
            synonyms={},
            intent_ids=[],
            entity_ids=[],
            spacy_model="unused",
        )


def test_build_pipeline_zero_shot_uses_serialized_settings(monkeypatch) -> None:
    config = SimpleNamespace(pipeline_type=PipelineType.ZERO_SHOT, llm_settings=SimpleNamespace(model_dump=lambda: {"api": "key"}))

    def fake_serializer(settings: Any) -> dict[str, Any]:  # pragma: no cover - captured by patch
        return {"api": "key"}

    monkeypatch.setattr(pipeline_utils, "_serialize_llm_settings", fake_serializer)

    captured: dict[str, Any] = {}

    def fake_zero_shot(*, intents, entities, synonyms, **kwargs: Any) -> object:
        captured["intents"] = intents
        captured["entities"] = entities
        captured["synonyms"] = synonyms
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(pipeline_utils, "create_zero_shot_pipeline", fake_zero_shot)

    pipeline_utils._build_pipeline_from_configuration(
        config=config,
        synonyms={"a": "b"},
        intent_ids=["order"],
        entity_ids=["item"],
        spacy_model="unused",
    )

    assert captured["intents"] == ["order"]
    assert captured["entities"] == ["item"]
    assert captured["synonyms"] == {"a": "b"}
    assert captured["kwargs"] == {"api": "key"}


def test_build_pipeline_ml_delegates(monkeypatch) -> None:
    config = SimpleNamespace(pipeline_type=PipelineType.ML, llm_settings=None)
    captured: dict[str, Any] = {}

    def fake_ml(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(pipeline_utils, "create_ml_pipeline", fake_ml)

    pipeline_utils._build_pipeline_from_configuration(
        config=config,
        synonyms={"x": "y"},
        intent_ids=[],
        entity_ids=[],
        spacy_model="en_core",
    )

    assert captured["spacy_model"] == "en_core"
    assert captured["synonyms"] == {"x": "y"}


def test_serialize_llm_settings_prefers_model_dump() -> None:
    settings = SimpleNamespace(model_dump=lambda: {"a": 1})
    assert pipeline_utils._serialize_llm_settings(settings) == {"a": 1}


def test_serialize_llm_settings_falls_back_to_dict() -> None:
    settings = SimpleNamespace(dict=lambda: {"b": 2})
    assert pipeline_utils._serialize_llm_settings(settings) == {"b": 2}