import pytest
from app.bot.nlu import pipeline_utils


class DummyComponent:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class DummyPipeline:
    def __init__(self, components):
        self.components = components

    def train(self, training_data, models_dir):
        self.training_data = training_data
        self.trained_in = models_dir


class DummySettings:
    SPACY_LANG_MODEL = "xx_test_md"
    MODELS_DIR = "/tmp/nlu_models"


class FakeIntent:
    def __init__(self, intentId, trainingData):
        self.intentId = intentId
        self.trainingData = trainingData


@pytest.mark.asyncio
async def test_create_ml_pipeline_uses_settings_spacy_model(monkeypatch):
    monkeypatch.setattr(pipeline_utils, "SpacyFeaturizer", DummyComponent)
    monkeypatch.setattr(pipeline_utils, "SklearnIntentClassifier", DummyComponent)
    monkeypatch.setattr(pipeline_utils, "CRFEntityExtractor", DummyComponent)
    monkeypatch.setattr(pipeline_utils, "SynonymReplacer", DummyComponent)
    monkeypatch.setattr(pipeline_utils, "NLUPipeline", DummyPipeline)
    monkeypatch.setattr(pipeline_utils, "list_synonyms", lambda: [])
    monkeypatch.setattr(pipeline_utils, "get_settings", lambda: DummySettings())
    pipeline = await pipeline_utils.create_ml_pipeline()
    assert isinstance(pipeline, DummyPipeline)
    assert pipeline.components[0].args[0] == "xx_test_md"


@pytest.mark.asyncio
async def test_train_pipeline_prepares_training_and_calls_train(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_utils, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(pipeline_utils.os.path, "exists", lambda p: False)
    created = {"path": None}

    def fake_makedirs(p):
        created["path"] = p

    monkeypatch.setattr(pipeline_utils.os, "makedirs", fake_makedirs)

    intents = [
        FakeIntent("greet", [{"text": "hi"}, {"text": "Hello"}]),
        FakeIntent("empty", [{"text": "  "}, {"text": ""}]),
    ]

    async def fake_list_intents():
        return intents

    monkeypatch.setattr(pipeline_utils, "list_intents", fake_list_intents)

    class TrainablePipeline(DummyPipeline):
        def __init__(self):
            super().__init__(components=[])
            self.called = False

        def train(self, training_data, models_dir):
            self.called = True
            self.training_data = training_data
            self.trained_in = models_dir

    async def fake_get_pipeline():
        return TrainablePipeline()

    monkeypatch.setattr(pipeline_utils, "get_pipeline", fake_get_pipeline)

    await pipeline_utils.train_pipeline()

    assert created["path"] == "/tmp/nlu_models"