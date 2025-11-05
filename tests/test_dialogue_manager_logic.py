import pytest
from types import SimpleNamespace
from app.bot.dialogue_manager.dialogue_manager import DialogueManager


class FakePipeline:
    def __init__(self):
        self.loaded = False

    def load(self, models_dir):
        self.loaded = True
        return True

    def process(self, data):
        # Return the nlu_result if present for deterministic testing
        return data.get('nlu_result') or {}


class Param:
    def __init__(self, name, type_, required, prompt=None):
        self.name = name
        self.type = type_
        self.required = required
        self.prompt = prompt or f"Please provide {name}"


class Intent:
    def __init__(self, intent_id, parameters=None, api_trigger=False, api_details=None, speech_response="ok"):
        self.intent_id = intent_id
        self.parameters = parameters or []
        self.api_trigger = api_trigger
        self.api_details = api_details
        self.speech_response = speech_response


class FakeState:
    def __init__(self, text):
        self.user_message = SimpleNamespace(text=text)
        self.parameters = []
        self.extracted_parameters = {}
        self.missing_parameters = []
        self.current_node = None
        self.bot_message = []
        self.nlu = {}
        self.complete = False

    def get_active_intent_id(self):
        return None


def make_dm(confidence_threshold=0.75):
    fallback = Intent('fallback')
    greet = Intent('greet', parameters=[Param('name', 'free_text', True)])
    intents = [fallback, greet]
    dm = DialogueManager(memory_saver=None, intents=intents, nlu_pipeline=FakePipeline(), fallback_intent_id='fallback', intent_confidence_threshold=confidence_threshold)
    return dm


def test_get_intent_id_and_confidence_slash():
    dm = make_dm()
    state = FakeState('/cancel')
    intent_id, conf = dm._get_intent_id_and_confidence(state, {})
    assert intent_id == 'cancel'
    assert conf == 1.0


def test_get_intent_id_and_confidence_low_confidence():
    dm = make_dm()
    state = FakeState('hello')
    nlu = {'intent': {'intent': 'greet', 'confidence': 0.5}}
    intent_id, conf = dm._get_intent_id_and_confidence(state, nlu)
    assert intent_id == 'fallback'
    assert conf == 1.0


def test_get_intent_id_and_confidence_high_confidence():
    dm = make_dm()
    state = FakeState('hello')
    nlu = {'intent': {'intent': 'greet', 'confidence': 0.9}}
    intent_id, conf = dm._get_intent_id_and_confidence(state, nlu)
    assert intent_id == 'greet'
    assert conf == 0.9


def test_handle_missing_parameters_prompts():
    dm = make_dm()
    state = FakeState('')
    # no extracted parameters -> missing required 'name'
    params = [Param('name', 'free_text', True)]
    state.extracted_parameters = {}
    updated = dm._handle_missing_parameters(params, state)
    assert 'name' in updated.missing_parameters
    assert updated.current_node == 'name'
    assert isinstance(updated.bot_message, list) and len(updated.bot_message) > 0


@pytest.mark.asyncio
async def test_process_cancel_intent():
    dm = make_dm()
    cancel_intent = Intent('cancel')
    state = FakeState('')
    state.intent = {'id': 'cancel'}

    # Simulate that _process_intent will set complete to True for cancel
    updated_state, active_intent = dm._process_intent(cancel_intent, cancel_intent, state)
    assert updated_state.complete
    assert updated_state.current_node is None
    assert active_intent.intent_id == 'cancel'


@pytest.mark.asyncio
async def test_process_intent_with_parameters():
    dm = make_dm()
    param = Param('name', 'free_text', True)
    intent = Intent('greet', parameters=[param])
    state = FakeState('John')

    # Simulate extracted_parameters empty and no missing parameters yet
    state.extracted_parameters = {}

    updated_state, active_intent = dm._process_intent(intent, intent, state)
    assert 'name' in [p['name'] for p in updated_state.parameters]
    # After processing missing parameters, name should be in missing_parameters
    assert 'name' in updated_state.missing_parameters


@pytest.mark.asyncio
async def test_handle_api_trigger_with_no_api():
    dm = make_dm()
    intent = Intent('greet')  # no api trigger
    state = FakeState('')
    state.extracted_parameters = {'name': 'test'}

    result = await dm._handle_api_trigger(intent, state)
    assert isinstance(result.bot_message, list)
    assert len(result.bot_message) > 0


@pytest.mark.asyncio
async def test_update_model_loads():
    dm = make_dm()
    assert not dm.nlu_pipeline.loaded
    dm.update_model('dummy_models_dir')
    assert dm.nlu_pipeline.loaded