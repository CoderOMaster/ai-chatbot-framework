from app.bot.dialogue_manager.dialogue_manager import DialogueManager


class DummyMS:
    pass


class DummyNLU:
    def __init__(self, ok):
        self.ok = ok
        self.loaded = None

    def load(self, models_dir):
        self.loaded = models_dir
        return self.ok


def make_dm(nlu):
    return DialogueManager(
        memory_saver=DummyMS(),
        intents=[],
        nlu_pipeline=nlu,
        fallback_intent_id="fallback",
        intent_confidence_threshold=0.5,
    )


def test_update_model_success_keeps_pipeline():
    nlu = DummyNLU(ok=True)
    dm = make_dm(nlu)
    dm.update_model("/models")
    assert dm.nlu_pipeline is nlu
    assert nlu.loaded == "/models"


def test_update_model_failure_sets_pipeline_none():
    nlu = DummyNLU(ok=False)
    dm = make_dm(nlu)
    dm.update_model("/models")
    assert dm.nlu_pipeline is None