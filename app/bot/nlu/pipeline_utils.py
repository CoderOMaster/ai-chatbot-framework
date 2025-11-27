import asyncio
import importlib
import os
from typing import Any, AsyncIterator, Dict, List, Optional

from app.admin.bots.schemas import NLUConfiguration
from app.admin.intents.store import IntentRepository
from app.bot.nlu.pipeline import NLUPipeline
from app.bot.nlu.featurizers import SpacyFeaturizer
from app.bot.nlu.intent_classifiers import SklearnIntentClassifier
from app.bot.nlu.entity_extractors import CRFEntityExtractor, SynonymReplacer
from app.bot.nlu.llm import ZeroShotNLUOpenAI
from app.admin.entities.store import stream_synonyms
from app.admin.bots.store import get_nlu_config
from app.config import get_app_config

# Cache compiled pipelines per bot name to avoid rebuilds on each request
_PIPELINE_CACHE: Dict[str, NLUPipeline] = {}
_PIPELINE_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_default_database() -> Any:
    """Obtain the application's default AsyncIOMotorDatabase instance.

    This mirrors other store modules and avoids importing app.database at
    module import time. Raises RuntimeError when a default database cannot
    be located; callers may provide explicit repositories/collections for
    easier testing.
    """
    try:
        db_mod = importlib.import_module("app.database")
        database_obj = getattr(db_mod, "database", None)
        if database_obj is None:
            raise RuntimeError("No default database found; please pass explicit collections")
        return database_obj
    except Exception as exc:
        raise RuntimeError("Unable to obtain default database; please pass explicit collections") from exc


async def stream_training_examples(intent_repo: Optional[IntentRepository] = None, batch_size: int = 1000) -> AsyncIterator[Dict[str, Any]]:
    """Stream individual training examples from the intents collection.

    Yields dicts shaped like training examples and sets the `intent` field to
    the intent id. Using a cursor with a configurable batch size avoids
    materialising the full intents collection in memory when exporting from
    MongoDB.
    """
    if intent_repo is None:
        db = _get_default_database()
        intent_repo = IntentRepository.from_database(db)

    # Access the underlying collection to stream documents
    cursor = intent_repo.collection.find({}, {"trainingData": 1, "intentId": 1}).batch_size(batch_size)
    async for intent_doc in cursor:
        intent_id = intent_doc.get("intentId")
        for example in intent_doc.get("trainingData", []) or []:
            text = example.get("text") if isinstance(example, dict) else None
            if not text or not isinstance(text, str) or text.strip() == "":
                continue
            # Yield a fresh dict so callers can mutate if needed
            out = dict(example)
            out["intent"] = intent_id
            yield out


async def create_ml_pipeline(
    nlu_config: NLUConfiguration,
    intent_repo: Optional[IntentRepository] = None,
    entity_collection: Optional[Any] = None,
    featurizer_cls=SpacyFeaturizer,
    classifier_cls=SklearnIntentClassifier,
    crf_cls=CRFEntityExtractor,
    synonym_cls=SynonymReplacer,
) -> NLUPipeline:
    """Create a traditional ML pipeline based on a typed NLUConfiguration.

    Synonyms are loaded via the async stream_synonyms generator to avoid
    loading the entire collection into memory at once.
    """
    components = []

    # Optionally include spaCy featurizer depending on settings
    if getattr(nlu_config, "traditional_settings", None) and getattr(nlu_config.traditional_settings, "use_spacy", True):
        components.append(featurizer_cls())

    components.append(classifier_cls())

    # Include CRF entity extractor if present in codebase (keeps zero-shot bots light)
    try:
        components.append(crf_cls())
    except Exception:
        # Fail gracefully if CRF extractor is not available / misconfigured
        pass

    # Create synonym replacer and populate its synonyms asynchronously
    replacer = synonym_cls({})
    synonyms: Dict[str, str] = {}

    async for item in stream_synonyms(collection=entity_collection):
        # stream_synonyms yields items with keys 'synonym' and 'value'
        synonyms[item["synonym"]] = item["value"]

    replacer.configure(synonyms)
    components.append(replacer)

    return NLUPipeline(components)


async def create_zero_shot_pipeline(
    nlu_config: NLUConfiguration,
    intent_repo: Optional[IntentRepository] = None,
    entity_collection: Optional[Any] = None,
    zero_shot_cls=ZeroShotNLUOpenAI,
    synonym_cls=SynonymReplacer,
) -> NLUPipeline:
    """Create a zero-shot pipeline using bot-specific LLM settings.

    The function reads LLM settings from the provided typed NLUConfiguration
    and streams intent/entity ids from the intents collection instead of
    loading full intent documents.
    """
    if intent_repo is None:
        db = _get_default_database()
        intent_repo = IntentRepository.from_database(db)

    # Collect intent ids and entity names by streaming intent documents
    intent_ids: List[str] = []
    entity_ids: List[str] = []

    cursor = intent_repo.collection.find({}, {"intentId": 1, "parameters": 1})
    async for intent_doc in cursor:
        if intent_doc.get("intentId"):
            intent_ids.append(intent_doc.get("intentId"))
        for param in intent_doc.get("parameters", []) or []:
            name = param.get("name") if isinstance(param, dict) else None
            if name:
                entity_ids.append(name)

    # Build kwargs for the zero-shot LLM component from NLUConfiguration.llm_settings
    llm_settings = getattr(nlu_config, "llm_settings", None) or {}
    # llm_settings may be a pydantic model; turn into dict if so
    try:
        settings_dict = llm_settings.model_dump()  # pydantic v2
    except Exception:
        try:
            settings_dict = llm_settings.dict()
        except Exception:
            settings_dict = dict(llm_settings or {})

    llm_kwargs = {
        "intents": intent_ids,
        "entities": entity_ids,
        "base_url": settings_dict.get("base_url"),
        "api_key": settings_dict.get("api_key"),
        "model_name": settings_dict.get("model_name"),
        "max_tokens": settings_dict.get("max_tokens"),
        "temperature": settings_dict.get("temperature"),
    }

    replacer = synonym_cls({})
    synonyms: Dict[str, str] = {}
    async for item in stream_synonyms(collection=entity_collection):
        synonyms[item["synonym"]] = item["value"]
    replacer.configure(synonyms)

    return NLUPipeline([zero_shot_cls(**llm_kwargs), replacer])


async def get_pipeline(
    bot_name: str = "default",
    intent_repo: Optional[IntentRepository] = None,
    entity_collection: Optional[Any] = None,
) -> NLUPipeline:
    """Return a cached or newly built NLUPipeline for the given bot name.

    The pipeline is cached per bot name to avoid repeated builds. Pipeline
    creation is guarded by an asyncio.Lock per name to prevent races when
    multiple callers request creation concurrently.
    """
    if bot_name in _PIPELINE_CACHE:
        return _PIPELINE_CACHE[bot_name]

    lock = _PIPELINE_LOCKS.setdefault(bot_name, asyncio.Lock())
    async with lock:
        # double-check after acquiring lock
        if bot_name in _PIPELINE_CACHE:
            return _PIPELINE_CACHE[bot_name]

        # Load typed NLU configuration for the bot
        raw_cfg = await get_nlu_config(bot_name)
        if raw_cfg is None:
            raise RuntimeError(f"No NLU configuration found for bot '{bot_name}'")

        # Ensure we have a typed NLUConfiguration instance
        if isinstance(raw_cfg, NLUConfiguration):
            nlu_cfg = raw_cfg
        else:
            try:
                nlu_cfg = NLUConfiguration.model_validate(raw_cfg)
            except Exception:
                # Fallback: try constructing from dict-like
                nlu_cfg = NLUConfiguration(**(raw_cfg or {}))

        if getattr(nlu_cfg, "pipeline_type", None) == "llm":
            pipeline = await create_zero_shot_pipeline(nlu_cfg, intent_repo=intent_repo, entity_collection=entity_collection)
        else:
            pipeline = await create_ml_pipeline(nlu_cfg, intent_repo=intent_repo, entity_collection=entity_collection)

        _PIPELINE_CACHE[bot_name] = pipeline
        return pipeline


async def train_pipeline(
    bot_name: str = "default",
    intent_repo: Optional[IntentRepository] = None,
    entity_collection: Optional[Any] = None,
    models_dir: Optional[str] = None,
) -> None:
    """Orchestrate NLU pipeline training for a bot.

    Training data is streamed from the intents collection to avoid loading
    all intent documents at once. The function will build a list of training
    examples (component trainers may still require an in-memory list) but
    avoids retrieving the full intents collection as a single list.
    """
    config = get_app_config()
    models_root = models_dir or getattr(config, "MODELS_DIR", "models")
    os.makedirs(models_root, exist_ok=True)

    if intent_repo is None:
        db = _get_default_database()
        intent_repo = IntentRepository.from_database(db)

    # Stream training examples into a list required by downstream trainers
    training_data: List[Dict[str, Any]] = []
    async for ex in stream_training_examples(intent_repo=intent_repo):
        training_data.append(ex)

    if not training_data:
        raise RuntimeError("No training examples found for training")

    pipeline = await get_pipeline(bot_name=bot_name, intent_repo=intent_repo, entity_collection=entity_collection)

    # Persist models into a bot-scoped directory
    model_path = os.path.join(models_root, bot_name)
    pipeline.train(training_data, model_path)