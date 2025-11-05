"""Trainer entrypoint module for batch training and model management."""
import argparse
import asyncio
import logging
import os

from nlu_service.pipeline import get_pipeline
from app.config import app_config

logger = logging.getLogger("nlu_service.trainer")


async def train(models_dir: str, dry_run: bool = False):
    pipeline = await get_pipeline()
    if dry_run:
        logger.info("Dry run: would train and save models to %s", models_dir)
        return
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
    # fetch and prepare training data via existing utilities
    from app.bot.nlu.pipeline_utils import train_pipeline

    await train_pipeline()


def main():
    parser = argparse.ArgumentParser("nlu-trainer")
    parser.add_argument("--models-dir", default=os.environ.get("MODEL_DIR", "/models"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(train(args.models_dir, args.dry_run))


if __name__ == "__main__":
    main()