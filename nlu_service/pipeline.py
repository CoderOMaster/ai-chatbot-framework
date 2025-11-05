"""Thin compatibility wrapper to expose pipeline.predict/load under nlu_service package."""
from app.bot.nlu.pipeline import NLUPipeline  # reuse existing implementation

# expose class name for imports
NLUPipeline = NLUPipeline

async def get_pipeline():
    from app.bot.nlu.pipeline_utils import get_pipeline as _get_pipeline

    return await _get_pipeline()


# provide predictive helper compatible with old imports
async def predict(message, pipeline: NLUPipeline):
    return pipeline.process(message)