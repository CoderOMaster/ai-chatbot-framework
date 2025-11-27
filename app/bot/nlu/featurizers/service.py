"""REST API service for spaCy featurizer microservice."""

import logging
import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import uvicorn

from app.bot.nlu.featurizers.spacy_featurizer import SpacyFeaturizer

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NLU Featurizer Service",
    description="spaCy-based NLU featurizer microservice",
    version="1.0.0",
)

# Configuration from environment
SPACY_MODEL_NAME = os.getenv("SPACY_MODEL_NAME", "en_core_web_sm")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")

# Configure logging
logging.basicConfig(level=LOG_LEVEL)

# Initialize featurizer
featurizer = SpacyFeaturizer(
    model_name=SPACY_MODEL_NAME,
    use_cache=True,
    parallelizable=True,
)


class TextInput(BaseModel):
    """Input model for text processing."""

    text: str = Field(..., min_length=1, description="Text to process")


class BatchTextInput(BaseModel):
    """Input model for batch text processing."""

    texts: List[str] = Field(..., min_length=1, description="List of texts to process")


class FeaturizerResponse(BaseModel):
    """Response model for featurizer output."""

    text: str
    tokens: List[str]
    lemmas: List[str]
    pos_tags: List[str]
    entities: List[Dict[str, Any]]


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    model_name: str
    model_loaded: bool
    cache_stats: Dict[str, int]


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize featurizer on startup."""
    logger.info(f"Starting NLU Featurizer Service with model: {SPACY_MODEL_NAME}")
    try:
        success = featurizer.load("")
        if not success:
            raise RuntimeError("Failed to load featurizer")
        logger.info("Featurizer loaded successfully")
    except Exception as e:
        logger.error(f"Failed to initialize featurizer: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Cleanup on shutdown."""
    logger.info("Shutting down NLU Featurizer Service")
    model = featurizer._get_model()
    model.clear_cache()


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint.
    
    Returns:
        HealthResponse with service status
    """
    health_info = featurizer.health_check()
    return HealthResponse(**health_info)


@app.post("/process", response_model=FeaturizerResponse)
async def process_text(input_data: TextInput) -> FeaturizerResponse:
    """Process a single text and extract features.
    
    Args:
        input_data: TextInput with text to process
        
    Returns:
        FeaturizerResponse with extracted features
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        message = {"text": input_data.text}
        result = featurizer.process(message)
        doc = result.get("spacy_doc")

        if doc is None:
            raise ValueError("Failed to process text")

        entities = [
            {
                "text": ent.text,
                "label": ent.label_,
                "start": ent.start_char,
                "end": ent.end_char,
            }
            for ent in doc.ents
        ]

        return FeaturizerResponse(
            text=input_data.text,
            tokens=[token.text for token in doc],
            lemmas=[token.lemma_ for token in doc],
            pos_tags=[token.pos_ for token in doc],
            entities=entities,
        )
    except Exception as e:
        logger.error(f"Error processing text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process_batch")
async def process_batch(input_data: BatchTextInput) -> Dict[str, Any]:
    """Process multiple texts concurrently.
    
    Args:
        input_data: BatchTextInput with list of texts
        
    Returns:
        Dictionary with list of processed results
        
    Raises:
        HTTPException: If batch processing fails
    """
    try:
        model = featurizer._get_model()
        docs = model.process_batch(input_data.texts, use_cache=True)

        results = []
        for text, doc in zip(input_data.texts, docs):
            entities = [
                {
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char,
                }
                for ent in doc.ents
            ]

            results.append(
                {
                    "text": text,
                    "tokens": [token.text for token in doc],
                    "lemmas": [token.lemma_ for token in doc],
                    "pos_tags": [token.pos_ for token in doc],
                    "entities": entities,
                }
            )

        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error processing batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/cache/clear")
async def clear_cache(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """Clear the document cache.
    
    Args:
        background_tasks: FastAPI background tasks
        
    Returns:
        Dictionary with status message
    """
    model = featurizer._get_model()
    background_tasks.add_task(model.clear_cache)
    return {"status": "cache clear scheduled"}


@app.get("/cache/stats")
async def cache_stats() -> Dict[str, Any]:
    """Get cache statistics.
    
    Returns:
        Dictionary with cache statistics
    """
    model = featurizer._get_model()
    return model.get_cache_stats()


@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint.
    
    Returns:
        Dictionary with service information
    """
    return {
        "service": "NLU Featurizer",
        "version": "1.0.0",
        "model": SPACY_MODEL_NAME,
        "endpoints": [
            "/health",
            "/process",
            "/process_batch",
            "/cache/stats",
            "/cache/clear",
        ],
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
    )