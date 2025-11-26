"""
NLU Pipeline Training Module

This module provides CLI/daemon job entrypoint for NLU model training.
It is designed to run as a background microservice or batch job, never on the request path.
"""

import os
import sys
import logging
from typing import Optional
import click
from pydantic_settings import BaseSettings

from app.admin.intents.store import list_intents
from app.bot.nlu.pipeline import NLUPipeline
from app.bot.nlu.featurizers import SpacyFeaturizer
from app.bot.nlu.intent_classifiers import SklearnIntentClassifier
from app.bot.nlu.entity_extractors import CRFEntityExtractor
from app.bot.nlu.entity_extractors import SynonymReplacer
from app.bot.nlu.llm import ZeroShotNLUOpenAI
from app.admin.entities.store import list_synonyms
from app.admin.bots.store import get_nlu_config
from app.config import app_config

logger = logging.getLogger(__name__)


class TrainingConfig(BaseSettings):
    """Configuration for NLU training job."""

    models_dir: str = app_config.MODELS_DIR
    training_type: str = "traditional"  # "traditional" or "llm"
    bot_id: str = "default"
    log_level: str = "INFO"

    class Config:
        env_prefix = "NLU_TRAINING_"
        case_sensitive = False


async def train_pipeline(
    models_dir: Optional[str] = None,
    training_type: str = "traditional",
    bot_id: str = "default",
) -> None:
    """
    Initiate NLU pipeline training as a background job.

    This function is designed to run as a CLI/daemon entrypoint and should never
    be called from the request path. It reads intents and entities from MongoDB,
    trains the specified pipeline type, and writes artifacts to MODELS_DIR.

    Args:
        models_dir: Directory to store trained models. Defaults to app_config.MODELS_DIR.
        training_type: Type of pipeline to train ("traditional" or "llm").
        bot_id: Bot identifier for multi-bot support.

    Raises:
        Exception: If no intents are found for training.
    """
    if models_dir is None:
        models_dir = app_config.MODELS_DIR

    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
        logger.info(f"Created models directory: {models_dir}")

    logger.info(f"Starting NLU pipeline training for bot_id={bot_id}, type={training_type}")

    # get all intents
    intents = await list_intents()
    if not intents:
        raise Exception("No intents found for training")

    logger.info(f"Found {len(intents)} intents for training")

    # prepare training data
    training_data = []
    for intent in intents:
        for example in intent.trainingData:
            if example.get("text", "").strip() == "":
                continue
            example["intent"] = intent.intentId
            training_data.append(example)

    logger.info(f"Prepared {len(training_data)} training examples")

    # initialize and train pipeline
    pipeline = await get_pipeline(training_type=training_type, bot_id=bot_id)
    pipeline.train(training_data, models_dir)

    logger.info(f"NLU pipeline training completed. Models saved to {models_dir}")


async def get_pipeline(
    training_type: str = "traditional",
    bot_id: str = "default",
) -> NLUPipeline:
    """
    Get the appropriate NLU pipeline based on configuration.

    Args:
        training_type: Type of pipeline ("traditional" or "llm").
        bot_id: Bot identifier for multi-bot support.

    Returns:
        Configured NLUPipeline instance.
    """
    nlu_config = await get_nlu_config(bot_id)

    if training_type == "traditional" or nlu_config.pipeline_type == "traditional":
        return await create_ml_pipeline(**nlu_config.traditional_settings.dict())

    if training_type == "llm" or nlu_config.pipeline_type == "llm":
        return await create_zero_shot_pipeline(**nlu_config.llm_settings.dict())

    raise ValueError(f"Unknown training type: {training_type}")


async def create_ml_pipeline(**kwargs) -> NLUPipeline:
    """
    Create a machine learning pipeline with traditional NLU components.

    Returns:
        NLUPipeline configured with spaCy, sklearn, CRF, and synonym replacement.
    """
    synonyms = await list_synonyms()
    return NLUPipeline(
        [
            SpacyFeaturizer(app_config.SPACY_LANG_MODEL),
            SklearnIntentClassifier(),
            CRFEntityExtractor(),
            SynonymReplacer(synonyms),
        ]
    )


async def create_zero_shot_pipeline(**kwargs) -> NLUPipeline:
    """
    Create a zero-shot LLM-based pipeline.

    Returns:
        NLUPipeline configured with OpenAI zero-shot NLU and synonym replacement.
    """
    intents = await list_intents()
    synonyms = await list_synonyms()

    intent_ids = []
    entity_ids = []

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
            ),
            SynonymReplacer(synonyms),
        ]
    )


@click.group()
def cli():
    """NLU Training CLI."""
    pass


@cli.command()
@click.option(
    "--models-dir",
    type=click.Path(),
    default=None,
    help="Directory to store trained models. Defaults to app_config.MODELS_DIR.",
)
@click.option(
    "--training-type",
    type=click.Choice(["traditional", "llm"]),
    default="traditional",
    help="Type of pipeline to train.",
)
@click.option(
    "--bot-id",
    type=str,
    default="default",
    help="Bot identifier for multi-bot support.",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Logging level.",
)
def train(
    models_dir: Optional[str],
    training_type: str,
    bot_id: str,
    log_level: str,
) -> None:
    """
    Train NLU pipeline as a background job.

    This command reads intents and entities from MongoDB, trains the specified
    pipeline type, and writes artifacts to MODELS_DIR. It is designed to run as
    a CLI entrypoint in a containerized environment and should never be called
    from the request path.

    Example:
        python -m app.bot.nlu.pipeline_utils train --training-type traditional --bot-id default
    """
    import asyncio

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"NLU Training CLI started with log_level={log_level}")

    try:
        asyncio.run(
            train_pipeline(
                models_dir=models_dir,
                training_type=training_type,
                bot_id=bot_id,
            )
        )
        logger.info("Training completed successfully")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Training failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()