import os
from typing import Any, Mapping, Sequence

from app.admin.bots.schemas import LLMSettings, NLUConfiguration, PipelineType
from app.admin.bots.store import BotRepository
from app.admin.entities.store import EntityRepository
from app.admin.intents.schemas import Intent
from app.admin.intents.store import IntentRepository
from app.bot.nlu.entity_extractors import CRFEntityExtractor, SynonymReplacer
from app.bot.nlu.featurizers import SpacyFeaturizer
from app.bot.nlu.intent_classifiers import SklearnIntentClassifier
from app.bot.nlu.llm import ZeroShotNLUOpenAI
from app.bot.nlu.pipeline import NLUPipeline


SynonymMapping = Mapping[str, str]


async def training_worker_entrypoint(
    *,
    intent_repository: IntentRepository,
    entity_repository: EntityRepository,
    bot_repository: BotRepository,
    models_dir: str,
    spacy_model: str,
    bot_name: str = "default",
) -> None:
    """Entrypoint for training workers to kick off pipeline training."""
    await train_pipeline(
        intent_repository=intent_repository,
        entity_repository=entity_repository,
        bot_repository=bot_repository,
        models_dir=models_dir,
        spacy_model=spacy_model,
        bot_name=bot_name,
    )


async def train_pipeline(
    *,
    intent_repository: IntentRepository,
    entity_repository: EntityRepository,
    bot_repository: BotRepository,
    models_dir: str,
    spacy_model: str,
    bot_name: str = "default",
) -> None:
    """Train a new NLU pipeline with injected data sources and storage location."""
    _ensure_directory_exists(models_dir)

    intents = await intent_repository.list_intents()
    if not intents:
        raise ValueError("No intents found for training")

    training_data = _prepare_training_examples(intents)
    synonyms = await entity_repository.list_synonyms()
    intent_ids, entity_ids = _extract_zero_shot_metadata(intents)
    nlu_config = await bot_repository.get_nlu_config(bot_name)

    pipeline = _build_pipeline_from_configuration(
        config=nlu_config,
        synonyms=synonyms,
        intent_ids=intent_ids,
        entity_ids=entity_ids,
        spacy_model=spacy_model,
    )

    pipeline.train(training_data, models_dir)


async def get_pipeline(
    *,
    pipeline_type: PipelineType | str = PipelineType.ML,
    spacy_model: str,
    synonyms: SynonymMapping | None = None,
    zero_shot_intents: Sequence[str] | None = None,
    zero_shot_entities: Sequence[str] | None = None,
    zero_shot_kwargs: Mapping[str, Any] | None = None,
) -> NLUPipeline:
    """Return a runtime pipeline that only loads prebuilt assets without any training work."""
    resolved_type = PipelineType(pipeline_type)
    synonym_dict = dict(synonyms or {})

    if resolved_type == PipelineType.ZERO_SHOT:
        if zero_shot_kwargs is None:
            raise ValueError("zero_shot_kwargs must be provided for zero-shot pipelines")
        return create_zero_shot_pipeline(
            intents=list(zero_shot_intents or []),
            entities=list(zero_shot_entities or []),
            synonyms=synonym_dict,
            **zero_shot_kwargs,
        )

    return create_ml_pipeline(spacy_model=spacy_model, synonyms=synonym_dict)


def create_ml_pipeline(*, spacy_model: str, synonyms: SynonymMapping) -> NLUPipeline:
    """Construct a traditional spaCy + sklearn + CRF pipeline."""
    return NLUPipeline(
        [
            SpacyFeaturizer(spacy_model),
            SklearnIntentClassifier(),
            CRFEntityExtractor(),
            SynonymReplacer(dict(synonyms)),
        ]
    )


def create_zero_shot_pipeline(
    *,
    intents: Sequence[str],
    entities: Sequence[str],
    synonyms: SynonymMapping,
    **llm_kwargs: Any,
) -> NLUPipeline:
    """Construct a zero-shot pipeline that wraps the configured LLM provider."""
    return NLUPipeline(
        [
            ZeroShotNLUOpenAI(
                intents=intents,
                entities=entities,
                **llm_kwargs,
            ),
            SynonymReplacer(dict(synonyms)),
        ]
    )


def _ensure_directory_exists(models_dir: str) -> None:
    """Ensure the provided models directory exists before training."""
    os.makedirs(models_dir, exist_ok=True)


def _prepare_training_examples(intents: Sequence[Intent]) -> list[dict[str, Any]]:
    """Flatten intent training data while filtering empty utterances."""
    training_data: list[dict[str, Any]] = []
    for intent in intents:
        for example in intent.trainingData:
            text = example.get("text") or ""
            if not text.strip():
                continue
            entry = {**example, "intent": intent.intentId}
            training_data.append(entry)
    return training_data


def _extract_zero_shot_metadata(intents: Sequence[Intent]) -> tuple[list[str], list[str]]:
    """Collect intent and entity identifiers that zero-shot components require."""
    intent_ids: list[str] = []
    entity_ids: list[str] = []
    for intent in intents:
        intent_ids.append(intent.intentId)
        entity_ids.extend(parameter.name for parameter in intent.parameters)
    return intent_ids, entity_ids


def _build_pipeline_from_configuration(
    *,
    config: NLUConfiguration,
    synonyms: SynonymMapping,
    intent_ids: Sequence[str],
    entity_ids: Sequence[str],
    spacy_model: str,
) -> NLUPipeline:
    """Create a pipeline instance that matches the supplied NLU configuration."""
    pipeline_type = PipelineType(config.pipeline_type)
    if pipeline_type == PipelineType.ZERO_SHOT:
        llm_settings = config.llm_settings
        if llm_settings is None:
            raise ValueError("LLM settings must be provided for zero-shot pipelines")
        return create_zero_shot_pipeline(
            intents=list(intent_ids),
            entities=list(entity_ids),
            synonyms=synonyms,
            **_serialize_llm_settings(llm_settings),
        )

    return create_ml_pipeline(spacy_model=spacy_model, synonyms=synonyms)


def _serialize_llm_settings(settings: LLMSettings) -> dict[str, Any]:
    """Serialize LLM settings in a version-agnostic way."""
    serializer = getattr(settings, "model_dump", None)
    if callable(serializer):
        return serializer()
    return settings.dict()