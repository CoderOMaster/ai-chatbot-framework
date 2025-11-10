import argparse
import asyncio
import logging
import os
from app.bot.nlu.pipeline_utils import train_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nlu_trainer")

async def main_async(args):
    if args.dry_run:
        logger.info("trainer dry run", extra={"models_dir": os.getenv("MODEL_DIR", "/models")})
        return 0
    await train_pipeline()
    logger.info("training complete")
    return 0

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--train", action="store_true", help="run training")
    p.add_argument("--dry-run", action="store_true", help="only validate setup")
    p.add_argument("--models-dir", default=os.getenv("MODEL_DIR", "/models"))
    return p.parse_args()

def main():
    args = parse_args()
    return asyncio.run(main_async(args))

if __name__ == "__main__":
    raise SystemExit(main())