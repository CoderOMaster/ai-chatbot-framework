from app.bot.dialogue_manager.dialogue_manager import DialogueManager


class DummyMS:
    pass


class DummyNLU:
    pass


def make_dm(threshold=0.5, fallback="fallback"):
    return DialogueManager(
        memory_saver=DummyMS(),
        intents=[],
        nlu_pipeline=DummyNLU(),
        fallback_intent_id=fallback,
        intent_confidence_threshold=threshold,
    )


class Curr:
    def __init__(self, text):
        self.user_message = type("U", (), {"text": text})


def test_get_intent_id_and_confidence_direct_command():
    dm = make_dm()
    s = Curr("/help")
    iid, conf = dm._get_intent_id_and_confidence(
        s, {"intent": {"intent": "greet", "confidence": 0.7}}
    )
    assert iid == "help" and conf == 1.0


def test_get_intent_id_and_confidence_threshold_fallback():
    dm = make_dm(threshold=0.8, fallback="fb")
    s = Curr("hello")
    iid, conf = dm._get_intent_id_and_confidence(
        s, {"intent": {"intent": "greet", "confidence": 0.5}}
    )
    assert iid == "fb" and conf == 1.0