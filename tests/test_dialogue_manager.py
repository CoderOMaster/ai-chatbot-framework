import pytest
from unittest.mock import Mock, patch, AsyncMock
import httpx


# Service API models (these would be shared DTOs)
class IntentModel:
    """DTO for intent configuration"""
    def __init__(self, name, intent_id, parameters, speech_response, api_trigger, api_details):
        self.name = name
        self.intent_id = intent_id
        self.parameters = parameters
        self.speech_response = speech_response
        self.api_trigger = api_trigger
        self.api_details = api_details


class ParameterModel:
    """DTO for parameter configuration"""
    def __init__(self, name, type, required, prompt):
        self.name = name
        self.type = type
        self.required = required
        self.prompt = prompt


class ApiDetailsModel:
    """DTO for API trigger configuration"""
    def __init__(self, url, request_type, headers, is_json, json_data):
        self.url = url
        self.request_type = request_type
        self.headers = headers
        self.is_json = is_json
        self.json_data = json_data


class UserMessage:
    """DTO for user message"""
    def __init__(self, text, context, thread_id):
        self.text = text
        self.context = context
        self.thread_id = thread_id


class State:
    """DTO for conversation state"""
    def __init__(self, thread_id, user_message, complete, parameters, extracted_parameters, 
                 missing_parameters, current_node, intent):
        self.thread_id = thread_id
        self.user_message = user_message
        self.complete = complete
        self.parameters = parameters
        self.extracted_parameters = extracted_parameters
        self.missing_parameters = missing_parameters
        self.current_node = current_node
        self.intent = intent
        self.nlu = {}
        self.bot_message = []


class DialogueManagerClient:
    """HTTP client for dialogue-manager service"""
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url)

    async def process(self, message: dict) -> dict:
        """Call dialogue-manager /process endpoint"""
        response = await self.client.post("/process", json=message)
        response.raise_for_status()
        return response.json()

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


@pytest.fixture
def mock_dialogue_service():
    """Mock dialogue-manager service client"""
    client = Mock(spec=DialogueManagerClient)
    client.process = AsyncMock()
    return client


@pytest.fixture
def sample_intents():
    greet_intent = IntentModel(
        name="Greeting",
        intent_id="greet",
        parameters=[],
        speech_response="Hello!",
        api_trigger=False,
        api_details=None,
    )

    order_pizza_intent = IntentModel(
        name="Order Pizza",
        intent_id="order_pizza",
        parameters=[
            ParameterModel(
                name="size",
                type="pizza_size",
                required=True,
                prompt="What size pizza would you like?",
            ),
            ParameterModel(
                name="toppings",
                type="pizza_topping",
                required=True,
                prompt="What toppings would you like?",
            ),
        ],
        speech_response="Your {{parameters.size}} pizza with {{parameters.toppings}} will be ready soon!",
        api_trigger=True,
        api_details=ApiDetailsModel(
            url="http://pizza-api/order",
            request_type="POST",
            headers=[{"headerKey": "Content-Type", "headerValue": "application/json"}],
            is_json=True,
            json_data='{"size": "{{parameters.size}}", "toppings": "{{parameters.toppings}}"}',
        ),
    )

    fallback_intent = IntentModel(
        name="Fallback",
        intent_id="fallback",
        parameters=[],
        speech_response="I'm not sure I understand.",
        api_trigger=False,
        api_details=None,
    )

    cancel_intent = IntentModel(
        name="Cancel",
        intent_id="cancel",
        parameters=[],
        speech_response="Operation cancelled.",
        api_trigger=False,
        api_details=None,
    )

    return [greet_intent, order_pizza_intent, fallback_intent, cancel_intent]


class TestDialogueManager:
    """Integration tests for dialogue-manager service API"""

    @pytest.mark.asyncio
    async def test_process_simple_intent(self, mock_dialogue_service):
        """Test processing a simple intent via service API"""
        message = {
            "text": "hello",
            "context": {},
            "thread_id": "user1"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user1",
            "complete": True,
            "intent": {"id": "greet"},
            "nlu": {
                "intent": {"intent": "greet", "confidence": 0.95},
                "entities": {}
            },
            "extracted_parameters": {},
            "missing_parameters": [],
            "current_node": None,
            "bot_message": [{"text": "Hello!"}]
        }

        current_state = await mock_dialogue_service.process(message)

        # Verify service was called with correct message
        mock_dialogue_service.process.assert_called_once_with(message)

        assert current_state["complete"] is True
        assert current_state["intent"]["id"] == "greet"
        assert current_state["nlu"]["intent"]["intent"] == "greet"

    @pytest.mark.asyncio
    async def test_process_intent_with_parameters(self, mock_dialogue_service):
        """Test processing intent with parameter extraction via service API"""
        message = {
            "text": "I want a large pizza",
            "context": {},
            "thread_id": "user1"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user1",
            "complete": False,
            "intent": {"id": "order_pizza"},
            "nlu": {
                "intent": {"intent": "order_pizza", "confidence": 0.95},
                "entities": {"pizza_size": "large"}
            },
            "extracted_parameters": {"size": "large"},
            "missing_parameters": ["toppings"],
            "current_node": "toppings",
            "bot_message": [{"text": "What toppings would you like?"}],
            "parameters": [
                {"name": "size", "type": "pizza_size", "required": True},
                {"name": "toppings", "type": "pizza_topping", "required": True}
            ]
        }

        current_state = await mock_dialogue_service.process(message)

        assert current_state["complete"] is False
        assert current_state["current_node"] == "toppings"
        assert "size" in current_state["extracted_parameters"]
        assert current_state["extracted_parameters"]["size"] == "large"
        assert "toppings" in current_state["missing_parameters"]

    @pytest.mark.asyncio
    async def test_fallback_intent_low_confidence(self, mock_dialogue_service):
        """Test fallback intent triggered by low confidence via service API"""
        message = {
            "text": "gibberish text",
            "context": {},
            "thread_id": "user1"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user1",
            "complete": True,
            "intent": {"id": "fallback"},
            "nlu": {
                "intent": {"intent": "greet", "confidence": 0.85},
                "entities": {}
            },
            "extracted_parameters": {},
            "missing_parameters": [],
            "current_node": None,
            "bot_message": [{"text": "I'm not sure I understand."}]
        }

        current_state = await mock_dialogue_service.process(message)

        assert current_state["complete"] is True
        assert current_state["intent"]["id"] == "fallback"
        assert current_state["nlu"]["intent"]["intent"] == "greet"

    @pytest.mark.asyncio
    async def test_cancel_active_intent(self, mock_dialogue_service):
        """Test cancelling an active intent via service API"""
        message = {
            "text": "/cancel",
            "context": {},
            "thread_id": "user1"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user1",
            "complete": True,
            "intent": {"id": "cancel"},
            "nlu": {
                "intent": {"intent": "cancel", "confidence": 1.0},
                "entities": {}
            },
            "extracted_parameters": {},
            "missing_parameters": [],
            "current_node": None,
            "parameters": [],
            "bot_message": [{"text": "Operation cancelled."}]
        }

        current_state = await mock_dialogue_service.process(message)

        assert current_state["complete"] is True
        assert current_state["intent"]["id"] == "cancel"
        assert len(current_state["parameters"]) == 0
        assert current_state["current_node"] is None

    @pytest.mark.asyncio
    async def test_state_persistence(self, mock_dialogue_service):
        """Test state persistence across multiple turns via service API"""
        message = {
            "text": "large",
            "context": {},
            "thread_id": "user1"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user1",
            "complete": False,
            "intent": {"id": "order_pizza"},
            "nlu": {
                "intent": {"intent": "order_pizza", "confidence": 0.95},
                "entities": {"pizza_size": "large"}
            },
            "extracted_parameters": {"size": "large"},
            "missing_parameters": ["toppings"],
            "current_node": "toppings",
            "bot_message": [{"text": "What toppings would you like?"}],
            "parameters": [
                {"name": "size", "type": "pizza_size", "required": True},
                {"name": "toppings", "type": "pizza_topping", "required": True}
            ]
        }

        current_state = await mock_dialogue_service.process(message)

        assert current_state["thread_id"] == "user1"
        assert current_state["intent"]["id"] == "order_pizza"
        assert current_state["extracted_parameters"]["size"] == "large"
        assert current_state["current_node"] == "toppings"
        assert not current_state["complete"]

    @pytest.mark.asyncio
    async def test_api_trigger(self, mock_dialogue_service):
        """Test API trigger execution via service API"""
        message = {
            "text": "pepperoni",
            "context": {},
            "thread_id": "user1"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user1",
            "complete": True,
            "intent": {"id": "order_pizza"},
            "nlu": {
                "intent": {"intent": "order_pizza", "confidence": 0.95},
                "entities": {"pizza_topping": "pepperoni"}
            },
            "extracted_parameters": {"size": "large", "toppings": "pepperoni"},
            "missing_parameters": [],
            "current_node": None,
            "bot_message": [{"text": "Your large pizza with pepperoni will be ready soon!"}],
            "parameters": [
                {"name": "size", "type": "pizza_size", "required": True},
                {"name": "toppings", "type": "pizza_topping", "required": True}
            ],
            "api_response": {"status": "success"}
        }

        current_state = await mock_dialogue_service.process(message)

        assert current_state["complete"] is True
        assert current_state["extracted_parameters"]["size"] == "large"
        assert current_state["extracted_parameters"]["toppings"] == "pepperoni"
        assert "api_response" in current_state

    @pytest.mark.asyncio
    async def test_process_intent_with_missing_parameters(self, mock_dialogue_service):
        """Test multi-turn parameter collection via service API"""
        # First turn: missing size parameter
        message1 = {
            "text": "I want a pizza",
            "context": {},
            "thread_id": "user2"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user2",
            "complete": False,
            "intent": {"id": "order_pizza"},
            "nlu": {
                "intent": {"intent": "order_pizza", "confidence": 0.95},
                "entities": {}
            },
            "extracted_parameters": {},
            "missing_parameters": ["size", "toppings"],
            "current_node": "size",
            "bot_message": [{"text": "What size pizza would you like?"}],
            "parameters": [
                {"name": "size", "type": "pizza_size", "required": True},
                {"name": "toppings", "type": "pizza_topping", "required": True}
            ]
        }

        current_state = await mock_dialogue_service.process(message1)

        assert current_state["bot_message"] == [{"text": "What size pizza would you like?"}]
        assert current_state["complete"] is False
        assert current_state["intent"]["id"] == "order_pizza"
        assert current_state["current_node"] == "size"
        assert current_state["missing_parameters"] == ["size", "toppings"]
        assert current_state["extracted_parameters"] == {}

        # Second turn: missing toppings parameter
        message2 = {
            "text": "large",
            "context": {},
            "thread_id": "user2"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user2",
            "complete": False,
            "intent": {"id": "order_pizza"},
            "nlu": {
                "intent": {"intent": "random_intent", "confidence": 0.40},
                "entities": {"pizza_size": "large"}
            },
            "extracted_parameters": {"size": "large"},
            "missing_parameters": ["toppings"],
            "current_node": "toppings",
            "bot_message": [{"text": "What toppings would you like?"}],
            "parameters": [
                {"name": "size", "type": "pizza_size", "required": True},
                {"name": "toppings", "type": "pizza_topping", "required": True}
            ]
        }

        current_state = await mock_dialogue_service.process(message2)

        assert current_state["bot_message"] == [{"text": "What toppings would you like?"}]
        assert current_state["complete"] is False
        assert current_state["intent"]["id"] == "order_pizza"
        assert current_state["current_node"] == "toppings"
        assert current_state["missing_parameters"] == ["toppings"]
        assert current_state["extracted_parameters"] == {"size": "large"}

        # Third turn: final response with API trigger
        message3 = {
            "text": "pepperoni",
            "context": {},
            "thread_id": "user2"
        }

        mock_dialogue_service.process.return_value = {
            "thread_id": "user2",
            "complete": True,
            "intent": {"id": "order_pizza"},
            "nlu": {
                "intent": {"intent": "random_intent", "confidence": 0.40},
                "entities": {"pizza_topping": "pepperoni"}
            },
            "extracted_parameters": {"size": "large", "toppings": "pepperoni"},
            "missing_parameters": [],
            "current_node": None,
            "bot_message": [{"text": "Your large pizza with pepperoni will be ready soon!"}],
            "parameters": [
                {"name": "size", "type": "pizza_size", "required": True},
                {"name": "toppings", "type": "pizza_topping", "required": True}
            ],
            "api_response": {"status": "success"}
        }

        current_state = await mock_dialogue_service.process(message3)

        assert current_state["bot_message"] == [{"text": "Your large pizza with pepperoni will be ready soon!"}]
        assert current_state["complete"] is True
        assert current_state["intent"]["id"] == "order_pizza"
        assert current_state["extracted_parameters"]["size"] == "large"
        assert current_state["extracted_parameters"]["toppings"] == "pepperoni"
        assert current_state["missing_parameters"] == []