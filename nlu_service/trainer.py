import argparse
import asyncio
import logging
import os

from ai_chatbot_common.config import get_settings
from app.bot.nlu.pipeline_utils import train_pipeline

logger = logging.getLogger("nlu_service.trainer")


def main():
    parser = argparse.ArgumentParser(description="NLU Trainer")
    parser.add_argument("--train", action="store_true", help="Run training")
    parser.add_argument("--models-dir", default=None, help="Models output directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if args.models_dir:
        # allow override via env in the process
        os.environ["MODELS_DIR"] = args.models_dir

    if args.dry_run:
        print("dry run: would train into", settings.MODELS_DIR)
        return 0

    if args.train:
        logger.info("starting training")
        asyncio.run(train_pipeline())
        logger.info("training finished")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())