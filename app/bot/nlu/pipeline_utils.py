from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.admin.bots.store import BotRepository
from app.admin.entities.store import EntityRepository
from app.admin.intents.store import IntentRepository
from app.bot.nlu.pipeline import NLUPipeline
from app.bot.nlu.featurizers import SpacyFeaturizer
from app.bot.nlu.intent_classifiers import SklearnIntentClassifier
from app.bot.nlu.entity_extractors import CRFEntityExtractor
from app.bot.nlu.entity_extractors import SynonymReplacer
from app.bot.nlu.llm import ZeroShotNLUOpenAI


async def train_pipeline(
    models_dir: str,
    intent_repo: IntentRepository,
    entity_repo: EntityRepository,
    bot_repo: BotRepository,
    spacy_model: str,
) -> None:
    """
    Train an NLU pipeline using injected repositories and persist artifacts to
    models_dir.

    This function is intended to run in a dedicated training worker. All
    external dependencies (intents, entities, nlu config) are provided via
    the repository abstractions so the worker can run without referencing
    application-global stores.
    """
    # Ensure models directory exists
    if not os.path.exists(models_dir):
        os.makedirs(models_dir, exist_ok=True)

    # fetch intents from the injected repository
    intents = await intent_repo.list_intents()
    if not intents:
        raise Exception("No intents found for training")

    # prepare training data
    training_data: List[Dict[str, Any]] = []
    for intent in intents:
        for example in intent.trainingData:
            if example.get("text", "").strip() == "":
                continue
            example["intent"] = intent.intentId
            training_data.append(example)

    # obtain nlu configuration from injected bot repository
    nlu_config = await bot_repo.get_nlu_config("default")

    # Build the appropriate pipeline for training. When building the
    # pipeline for training we allow the helpers to fetch additional data
    # (intent ids / synonyms) from the provided repositories.
    if nlu_config.pipeline_type == "traditional":
        pipeline = await create_ml_pipeline(spacy_model=spacy_model, entity_repo=entity_repo)
    elif nlu_config.pipeline_type == "llm":
        pipeline = await create_zero_shot_pipeline(
            spacy_model=spacy_model,
            intent_repo=intent_repo,
            entity_repo=entity_repo,
            **nlu_config.llm_settings.dict(),
        )
    else:
        raise ValueError(f"Unsupported pipeline type: {nlu_config.pipeline_type}")

    # Train and persist
    pipeline.train(training_data, models_dir)


async def get_pipeline(
    pipeline_type: str,
    spacy_model: str,
    *,
    synonyms: Optional[Dict[str, str]] = None,
    intent_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    **kwargs: Any,
) -> NLUPipeline:
    """
    Construct an NLU pipeline for runtime use.

    IMPORTANT: This factory never performs any training or talks to admin
    stores. All data required for runtime components (intent ids, entity
    ids, synonym maps, etc.) must be supplied by the caller so the runtime
    image does not depend on admin services.
    """
    if pipeline_type == "traditional":
        return await create_ml_pipeline(
            spacy_model=spacy_model,
            synonyms=synonyms,
        )
    if pipeline_type == "llm":
        return await create_zero_shot_pipeline(
            spacy_model=spacy_model,
            intent_ids=intent_ids or [],
            entity_ids=entity_ids or [],
            synonyms=synonyms,
            **kwargs,
        )
    raise ValueError(f"Unsupported pipeline type: {pipeline_type}")


async def create_ml_pipeline(
    *,
    spacy_model: str,
    entity_repo: Optional[EntityRepository] = None,
    synonyms: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> NLUPipeline:
    """
    Create a traditional ML pipeline.

    If synonyms are not provided but an EntityRepository is injected, the
    repository will be queried to obtain synonyms. Otherwise the provided
    synonyms mapping (or empty dict) will be used.
    """
    if synonyms is None and entity_repo is not None:
        synonyms = await entity_repo.list_synonyms()

    return NLUPipeline(
        [
            SpacyFeaturizer(spacy_model),
            SklearnIntentClassifier(),
            CRFEntityExtractor(),
            SynonymReplacer(synonyms or {}),
        ]
    )


async def create_zero_shot_pipeline(
    *,
    spacy_model: str,
    intent_repo: Optional[IntentRepository] = None,
    entity_repo: Optional[EntityRepository] = None,
    intent_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    synonyms: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> NLUPipeline:
    """
    Create a zero-shot pipeline.

    If intent_ids/entity_ids are not provided and intent_repo/entity_repo are
    injected, the repository will be queried to obtain the necessary ids.
    This helper does not perform training; for training use the training
    entrypoint which may call this helper with repository access.
    """
    # Fetch intent ids if missing and an intent repository is available
    if intent_ids is None and intent_repo is not None:
        intents = await intent_repo.list_intents()
        intent_ids = [intent.intentId for intent in intents]

    # Fetch synonyms if missing and an entity repository is available
    if synonyms is None and entity_repo is not None:
        synonyms = await entity_repo.list_synonyms()

    # Determine entity ids if not provided
    if entity_ids is None and intent_repo is not None:
        # derive entity ids from intent parameters
        intents = await intent_repo.list_intents()
        entity_set = set()
        for intent in intents:
            for parameter in intent.parameters:
                entity_set.add(parameter.name)
        entity_ids = list(entity_set)

    return NLUPipeline(
        [
            ZeroShotNLUOpenAI(
                intents=intent_ids or [],
                entities=entity_ids or [],
                **kwargs,
            ),
            SynonymReplacer(synonyms or {}),
        ]
    )