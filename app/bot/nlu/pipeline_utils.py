import os
import logging
from typing import Dict, Any, List

from app.bot.nlu.pipeline import NLUPipeline
from app.admin.intents.store import list_intents
from app.admin.entities.store import list_synonyms
from app.admin.bots.store import get_nlu_config
from ai_chatbot_common.config import get_settings

logger = logging.getLogger(__name__)

# Keep monkeypatch-friendly names at module scope for tests
try:  # pragma: no cover - optional at import time
    from app.bot.nlu.featurizers import SpacyFeaturizer  # type: ignore
    from app.bot.nlu.intent_classifiers import SklearnIntentClassifier  # type: ignore
    from app.bot.nlu.entity_extractors import CRFEntityExtractor  # type: ignore
    from app.bot.nlu.entity_extractors import SynonymReplacer  # type: ignore
except Exception:  # pragma: no cover - allow tests to monkeypatch these names
    SpacyFeaturizer = None  # type: ignore
    SklearnIntentClassifier = None  # type: ignore
    CRFEntityExtractor = None  # type: ignore
    SynonymReplacer = None  # type: ignore

# LLM zero-shot component optional
try:  # pragma: no cover
    from app.bot.nlu.llm import ZeroShotNLUOpenAI  # type: ignore
except Exception:  # pragma: no cover
    ZeroShotNLUOpenAI = None  # type: ignore


class RemoteNLUPipeline(NLUPipeline):
    """Lightweight NLUPipeline adapter that forwards inference to an HTTP endpoint.

    Keeps the same interface as NLUPipeline but does not load any local models.
    Endpoint should accept POST {"text": "..."} and return {"intent": {...}, "entities": {...}}.
    """

    def __init__(self, endpoint: str):
        super().__init__()
        self.endpoint = endpoint

    def load(self, model_path: str) -> bool:  # type: ignore[override]
        # Nothing to load for remote pipeline; consider it always ready.
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        import requests

        text = message.get("text", "")
        try:
            resp = requests.post(self.endpoint, json={"text": text}, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"RemoteNLUPipeline error calling {self.endpoint}: {e}")
            # Fallback to neutral output to avoid crashing the conversation loop
            return {"intent": {"intent": "fallback", "confidence": 0.0}, "entities": {}}
        return {
            "intent": data.get("intent"),
            "entities": data.get("entities", {}),
        }


async def train_pipeline():
    """
    Initiate NLU pipeline training
    :return:
    """
    settings = get_settings()
    models_dir = settings.MODELS_DIR

    if not os.path.exists(models_dir):
        os.makedirs(models_dir)

    # get all intents
    intents = await list_intents()
    if not intents:
        raise Exception("No intents found for training")

    # prepare training data
    training_data: List[Dict[str, Any]] = []
    for intent in intents:
        for example in intent.trainingData:
            if example.get("text").strip() == "":
                continue
            example["intent"] = intent.intentId
            training_data.append(example)

    # initialize and train pipeline
    pipeline = await get_pipeline()
    pipeline.train(training_data, models_dir)


async def get_pipeline():
    # Prefer remote forwarding to avoid loading heavy models in core API
    endpoint = os.getenv("MODEL_FORWARDING_ENDPOINT") or os.getenv("NLU_FORWARDING_ENDPOINT")
    if endpoint:
        logger.info(f"Using RemoteNLUPipeline forwarding to: {endpoint}")
        return RemoteNLUPipeline(endpoint)

    nlu_config = await get_nlu_config("default")
    if nlu_config.pipeline_type == "traditional":
        return await create_ml_pipeline(**nlu_config.traditional_settings.dict())
    if nlu_config.pipeline_type == "llm":
        return await create_zero_shot_pipeline(**nlu_config.llm_settings.dict())


async def create_ml_pipeline(**kwargs):
    """
    Create a machine learning pipeline
    :return:
    """
    # Resolve possibly-lazy classes allowing tests to monkeypatch names
    global SpacyFeaturizer, SklearnIntentClassifier, CRFEntityExtractor, SynonymReplacer
    if SpacyFeaturizer is None:  # pragma: no cover
        from app.bot.nlu.featurizers import SpacyFeaturizer as _SF
        SpacyFeaturizer = _SF  # type: ignore
    if SklearnIntentClassifier is None:  # pragma: no cover
        from app.bot.nlu.intent_classifiers import SklearnIntentClassifier as _IC
        SklearnIntentClassifier = _IC  # type: ignore
    if CRFEntityExtractor is None:  # pragma: no cover
        from app.bot.nlu.entity_extractors import CRFEntityExtractor as _CRF
        CRFEntityExtractor = _CRF  # type: ignore
    if SynonymReplacer is None:  # pragma: no cover
        from app.bot.nlu.entity_extractors import SynonymReplacer as _SR
        SynonymReplacer = _SR  # type: ignore

    synonyms = await list_synonyms()
    settings = get_settings()
    return NLUPipeline(
        [
            SpacyFeaturizer(settings.SPACY_LANG_MODEL),  # type: ignore[misc]
            SklearnIntentClassifier(),  # type: ignore[misc]
            CRFEntityExtractor(),  # type: ignore[misc]
            SynonymReplacer(synonyms),  # type: ignore[misc]
        ]
    )


async def create_zero_shot_pipeline(**kwargs):
    """
    Create a zero shot pipeline
    :return:
    """
    global ZeroShotNLUOpenAI, SynonymReplacer
    if ZeroShotNLUOpenAI is None:  # pragma: no cover
        from app.bot.nlu.llm import ZeroShotNLUOpenAI as _ZS
        ZeroShotNLUOpenAI = _ZS  # type: ignore
    if SynonymReplacer is None:  # pragma: no cover
        from app.bot.nlu.entity_extractors import SynonymReplacer as _SR
        SynonymReplacer = _SR  # type: ignore

    intents = await list_intents()
    synonyms = await list_synonyms()

    intent_ids: List[str] = []
    entity_ids: List[str] = []

    for intent in intents:
        intent_ids.append(intent.intentId)
        for parameter in intent.parameters:
            entity_ids.append(parameter.name)

    return NLUPipeline(
        [
            ZeroShotNLUOpenAI(
                intents=intent_ids,
                entities=entity_ids,
                **kwargs,
            ),  # type: ignore[misc]
            SynonymReplacer(synonyms),  # type: ignore[misc]
        ]
    )