import logging
from typing import Any, Dict, List, Optional
from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class ZeroShotNLUOpenAI(NLUComponent):
    """
    Deprecated in favor of a stateless Lambda handler.

    This class remains as a thin adapter that forwards to the Lambda contract.
    """

    def __init__(
        self,
        intents: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        **kwargs,
    ):
        self.intents = intents or []
        self.entities = entities or []

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        pass

    def load(self, model_path: str) -> bool:
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Minimal local fallback: no LLM call here. The event-driven Lambda should be used instead.
        """
        if not message.get("text"):
            logger.warning("Message does not contain 'text' key. Skipping processing.")
            return message

        # Preserve original keys to avoid breaking pipeline
        message.setdefault("intent", {"intent": None, "confidence": 0.0})
        message.setdefault("intent_ranking", [])
        message.setdefault("entities", {})
        logger.info("ZeroShotNLUOpenAI local adapter no-op. Use lambda_handlers.llm.zero_shot.handler")
        return message