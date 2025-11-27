import asyncio
import json
from datetime import datetime
from typing import Any, Dict

import pytest

import app.bot.nlu.pipeline_utils as pipeline_utils


class FakeResponse:
    def __init__(self, data: Any, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeAsyncClient:
    def __init__(self, responses: Dict[str, Any]):
        # responses keyed by url
        self.responses = responses
        self.last_get_args = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        # simplistic matching: use url only
        self.last_get_args = (url, params)
        data = self.responses.get(url, self.responses.get("default", []))
        return FakeResponse(data)


@pytest.mark.asyncio
async def test_pipeline_api_client_methods(monkeypatch):
    """
    Validate PipelineAPIClient.list_intents/list_synonyms/get_nlu_config use httpx and return JSON.
    """
    base = "http://internal-api"
    client = pipeline_utils.PipelineAPIClient(base_url=base)

    responses = {
        f"{base}/admin/intents": [{"intentId": "greet"}],
        f"{base}/admin/entities/synonyms": [{"entity": "city"}],
        f"{base}/admin/bots/default/nlu-config": {"pipeline_type": "traditional"},
    }

    def fake_async_client_factory(resps):
        def _factory(*args, **kwargs):
            return FakeAsyncClient(resps)

        return _factory

    monkeypatch.setattr(pipeline_utils.httpx, "AsyncClient", fake_async_client_factory(responses))

    intents = await client.list_intents(bot_id="default")
    synonyms = await client.list_synonyms(bot_id="default")
    config = await client.get_nlu_config(bot_id="default")

    assert intents == [{"intentId": "greet"}]
    assert synonyms == [{"entity": "city"}]
    assert config == {"pipeline_type": "traditional"}


@pytest.mark.asyncio
async def test_create_ml_pipeline_constructs_pipeline(monkeypatch):
    """
    create_ml_pipeline should build an NLUPipeline with expected components and forward synonyms to SynonymReplacer.
    """
    # Prepare fake synonyms
    fake_synonyms = [{"a": 1}]

    class FakeAPI:
        async def list_synonyms(self, bot_id: str = "default"):
            return fake_synonyms

    # Capture what NLUPipeline receives
    captured = {}

    class FakeNLUPipeline:
        def __init__(self, components):
            captured['components'] = components

    # Replace classes used to construct the pipeline with simple factories
    monkeypatch.setattr(pipeline_utils, "_api_client", FakeAPI())
    monkeypatch.setattr(pipeline_utils, "NLUPipeline", FakeNLUPipeline)

    # Create simplistic component factories to make identity checks
    monkeypatch.setattr(pipeline_utils, "SpacyFeaturizer", lambda model: f"spacy:{model}")
    monkeypatch.setattr(pipeline_utils, "SklearnIntentClassifier", lambda: "sklearn")
    monkeypatch.setattr(pipeline_utils, "CRFEntityExtractor", lambda: "crf")
    monkeypatch.setattr(pipeline_utils, "SynonymReplacer", lambda syn: ("synonym_replacer", syn))
    # Provide app_config attribute
    monkeypatch.setattr(pipeline_utils.app_config, "SPACY_LANG_MODEL", "en_core_web_sm", raising=False)

    pipeline = await pipeline_utils.create_ml_pipeline(bot_id="default")

    comps = captured['components']
    assert comps[0] == "spacy:en_core_web_sm"
    assert comps[1] == "sklearn"
    assert comps[2] == "crf"
    assert comps[3] == ("synonym_replacer", fake_synonyms)


@pytest.mark.asyncio
async def test_create_zero_shot_pipeline_constructs_pipeline(monkeypatch):
    """
    create_zero_shot_pipeline should collect intent and entity ids and instantiate ZeroShotNLUOpenAI with them.
    """
    intents = [
        {
            "intentId": "book_flight",
            "parameters": [{"name": "from"}, {"name": "to"}],
        }
    ]
    synonyms = [{"s": 1}]

    class FakeAPI:
        async def list_intents(self, bot_id: str = "default"):
            return intents

        async def list_synonyms(self, bot_id: str = "default"):
            return synonyms

    captured = {}

    class FakeNLUPipeline:
        def __init__(self, components):
            captured['components'] = components

    def fake_zero_shot(**kwargs):
        captured['zero_shot_kwargs'] = kwargs
        return "zero_shot_component"

    monkeypatch.setattr(pipeline_utils, "_api_client", FakeAPI())
    monkeypatch.setattr(pipeline_utils, "NLUPipeline", FakeNLUPipeline)
    monkeypatch.setattr(pipeline_utils, "ZeroShotNLUOpenAI", fake_zero_shot)
    monkeypatch.setattr(pipeline_utils, "SynonymReplacer", lambda s: ("syn", s))

    pipeline = await pipeline_utils.create_zero_shot_pipeline(bot_id="default", temperature=0.2)

    comps = captured['components']
    # zero_shot component should be first and synonym replacer second
    assert comps[0] == "zero_shot_component"
    assert comps[1] == ("syn", synonyms)

    # check zero_shot kwargs contained intents and entities lists
    zs_kwargs = captured['zero_shot_kwargs']
    assert zs_kwargs['intents'] == ["book_flight"]
    assert set(zs_kwargs['entities']) == {"from", "to"}
    assert zs_kwargs['temperature'] == 0.2


@pytest.mark.asyncio
async def test_enqueue_training_job_sends_message_and_returns_job_id(monkeypatch):
    """
    enqueue_training_job should create a job via job tracker and send a message to SQS.
    """
    # fake job tracker
    class FakeJobTracker:
        def create_job(self, bot_id: str):
            assert bot_id == "mybot"
            return "job-123"

    fake_sent = {}

    class FakeSQSClient:
        def send_message(self, QueueUrl, MessageBody):
            fake_sent['QueueUrl'] = QueueUrl
            fake_sent['MessageBody'] = MessageBody
            return {"MessageId": "m1"}

    monkeypatch.setattr(pipeline_utils, "_job_tracker", FakeJobTracker())
    monkeypatch.setattr(pipeline_utils, "_get_sqs_client", lambda: FakeSQSClient())
    monkeypatch.setattr(pipeline_utils.app_config, "TRAINING_QUEUE_URL", "https://sqs.fake/queue", raising=False)

    job_id = await pipeline_utils.enqueue_training_job(bot_id="mybot")
    assert job_id == "job-123"
    assert fake_sent['QueueUrl'] == "https://sqs.fake/queue"
    # MessageBody should include our job id
    assert "job-123" in fake_sent['MessageBody']


@pytest.mark.asyncio
async def test_train_pipeline_success(monkeypatch, tmp_path):
    """
    train_pipeline should progress through steps, call pipeline.train, and register model on success.
    """
    bot_id = "bot1"
    job_id = "job-xyz"
    models_dir = str(tmp_path / "models")

    # Fake job tracker that records status updates
    updates = []

    class FakeJobTracker:
        def create_job(self, b):
            return job_id

        def update_job_status(self, jid, status, progress=0, error=None):
            updates.append((jid, status, progress, error))

        def get_job_status(self, jid):
            return {"job_id": jid, "status": updates[-1][1].value if updates else pipeline_utils.TrainingJobStatus.PENDING.value}

    # Fake api client returns one intent with training data
    intents = [
        {"intentId": "i1", "trainingData": [{"text": "hello"}, {"text": ""}]}
    ]

    class FakeAPIClient:
        async def list_intents(self, bot_id_inner: str = "default"):
            assert bot_id_inner == bot_id
            return intents

        async def get_nlu_config(self, bot_id_inner: str = "default"):
            return {"pipeline_type": "traditional"}

    # Fake pipeline with train method
    train_called = {}

    class FakePipeline:
        def train(self, training_data, model_path):
            train_called['data'] = training_data
            train_called['path'] = model_path

    async def fake_get_pipeline(bid: str = "default"):
        assert bid == bot_id
        return FakePipeline()

    registered = {}

    class FakeModelRegistry:
        def register_model(self, model_id, version, pipeline_type, model_path, metadata=None):
            registered['model_id'] = model_id
            registered['version'] = version
            registered['pipeline_type'] = pipeline_type
            registered['model_path'] = model_path
            registered['metadata'] = metadata

    monkeypatch.setattr(pipeline_utils, "_job_tracker", FakeJobTracker())
    monkeypatch.setattr(pipeline_utils, "_api_client", FakeAPIClient())
    monkeypatch.setattr(pipeline_utils, "get_pipeline", fake_get_pipeline)
    monkeypatch.setattr(pipeline_utils, "_model_registry", FakeModelRegistry())
    monkeypatch.setattr(pipeline_utils.app_config, "MODELS_DIR", models_dir, raising=False)

    # Ensure os.path.exists returns False to force os.makedirs call; monkeypatch os.makedirs to no-op
    monkeypatch.setattr(pipeline_utils.os.path, "exists", lambda p: False)
    monkeypatch.setattr(pipeline_utils.os, "makedirs", lambda p: None)

    # Run training
    await pipeline_utils.train_pipeline(bot_id=bot_id, job_id=job_id)

    # Ensure training called with filtered training data (empty text filtered)
    assert train_called['data'] == [{"text": "hello", "intent": "i1"}]
    assert train_called['path'] == models_dir

    # Ensure model registry was used and metadata contains job_id
    assert registered['model_id'] == bot_id
    assert registered['pipeline_type'] == "traditional"
    assert registered['model_path'] == models_dir
    assert registered['metadata']["job_id"] == job_id

    # Check job updates included COMPLETED
    assert any(u[1] == pipeline_utils.TrainingJobStatus.COMPLETED for u in updates)


@pytest.mark.asyncio
async def test_train_pipeline_no_intents_updates_failed(monkeypatch):
    """
    If no intents are returned training should fail and job status be updated to FAILED.
    """
    bot_id = "bot2"
    job_id = "job-nointents"

    status_updates = []

    class FakeJobTracker:
        def create_job(self, b):
            return job_id

        def update_job_status(self, jid, status, progress=0, error=None):
            status_updates.append((jid, status, progress, error))

    class FakeAPIClient:
        async def list_intents(self, bot_id_inner: str = "default"):
            return []

        async def get_nlu_config(self, bot_id_inner: str = "default"):
            return {"pipeline_type": "traditional"}

    monkeypatch.setattr(pipeline_utils, "_job_tracker", FakeJobTracker())
    monkeypatch.setattr(pipeline_utils, "_api_client", FakeAPIClient())

    # Patch get_pipeline to avoid network calls if reached
    async def fake_get_pipeline(bid: str = "default"):
        return None

    monkeypatch.setattr(pipeline_utils, "get_pipeline", fake_get_pipeline)

    with pytest.raises(Exception):
        await pipeline_utils.train_pipeline(bot_id=bot_id, job_id=job_id)

    # Ensure last update was FAILED
    assert status_updates
    assert status_updates[-1][1] == pipeline_utils.TrainingJobStatus.FAILED
    assert status_updates[-1][3] is not None


def test_get_job_status_and_get_latest_model(monkeypatch):
    """
    get_job_status and get_latest_model should return results from the trackers/registry.
    """
    monkeypatch.setattr(pipeline_utils._job_tracker, "get_job_status", lambda jid: {"job_id": jid, "status": "done"})
    monkeypatch.setattr(pipeline_utils._model_registry, "get_latest_model", lambda mid: {"model_id": mid, "version": "v1"})

    js = pipeline_utils.get_job_status("j1")
    lm = pipeline_utils.get_latest_model("botA")

    assert js == {"job_id": "j1", "status": "done"}
    assert lm == {"model_id": "botA", "version": "v1"}