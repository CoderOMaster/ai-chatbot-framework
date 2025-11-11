import argparse
import asyncio
import logging
import os
from app.bot.nlu.pipeline_utils import train_pipeline

logger = logging.getLogger("nlu_trainer")

async def _main(args):
    if args.dry_run:
        logger.info("trainer dry run ok")
        return
    await train_pipeline()
    logger.info("training complete")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--train", action="store_true")
    p.add_argument("--models-dir", default=os.environ.get("MODEL_DIR", "/models"))
    p.add_argument("--dry_run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.train and not args.dry_run:
        logger.info("nothing to do; pass --train or --dry_run")
        return
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()