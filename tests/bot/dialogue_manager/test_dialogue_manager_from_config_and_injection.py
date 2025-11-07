import types
import pytest

from app.bot.dialogue_manager.dialogue_manager import DialogueManager


class DummyDB:
    def get_collection(self, name):
        class C:
            async def insert_one(self, d):
                return None
        return C()


class DummyClient:
    def __init__(self):
        self.db = DummyDB()
    def get_database(self, name):
        return self.db


@pytest.mark.asyncio
async def test_from_config_uses_injected_db_over_client(monkeypatch):
    # Prepare injected dummy client (MemorySaverMongo will call get_database on it)
    injected = DummyClient()

    # Patch stores and pipeline
    async def fake_list_intents():
        class D:
            intentId = "fallback"
            name = "fallback"
            speechResponse = "ok"
            userDefined = True
            apiTrigger = False
            parameters = []
        return [D()]

    async def fake_get_pipeline():
        class P:
            def load(self, *a, **k):
                return True
            def process(self, d):
                return {"intent": {"intent": "fallback", "confidence": 1.0}, "entities": {}}
        return P()

    class Settings:
        DEFAULT_FALLBACK_INTENT_NAME = "fallback"
        MODELS_DIR = "/tmp/models"

    async def fake_get_bot(name):
        class S: 
            class T: 
                intent_detection_threshold = 0.5
            traditional_settings = T()
        return types.SimpleNamespace(nlu_config=S())

    import app.bot.dialogue_manager.dialogue_manager as mod
    monkeypatch.setattr(mod, "list_intents", fake_list_intents)
    monkeypatch.setattr(mod, "get_pipeline", fake_get_pipeline)
    monkeypatch.setattr(mod, "get_settings", lambda: Settings())
    monkeypatch.setattr(mod, "get_bot", fake_get_bot)

    dm = await DialogueManager.from_config(db_or_client=injected)
    # MemorySaverMongo should have been constructed with the injected object
    assert dm.memory_saver is not None
    # It should have a db attribute originating from our DummyClient
    assert hasattr(dm.memory_saver, "db") and isinstance(dm.memory_saver.db, DummyDB)


@pytest.mark.asyncio
async def test_update_model_sets_pipeline_none_when_load_fails(monkeypatch):
    class DummyPipeline:
        def __init__(self):
            self.loaded = False
        def load(self, *a, **k):
            return False
    dm = DialogueManager(memory_saver=None, intents=[], nlu_pipeline=DummyPipeline(), fallback_intent_id="fallback", intent_confidence_threshold=0.5)
    dm.update_model("/path")
    assert dm.nlu_pipeline is None