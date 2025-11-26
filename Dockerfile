# Multi-stage Dockerfile for chatbot microservices
# Supports admin-training-api, nlu-training-worker, dialogue-manager-service, and legacy-fastapi-backend
# Build: docker build -t chatbot-service:latest .
# Run admin training API: docker run -e SERVICE=admin-training-api -p 8000:8000 chatbot-service:latest
# Run training worker: docker run -e SERVICE=training-worker chatbot-service:latest
# Run dialogue manager: docker run -e SERVICE=dialogue-manager -p 8000:8000 chatbot-service:latest
# Run monolith: docker run -e SERVICE=fastapi-backend -p 8000:8000 chatbot-service:latest

FROM --platform=linux/x86_64 python:3.11-slim

WORKDIR /app

# Install system dependencies for MongoDB drivers and ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create models directory for NLU artifacts
RUN mkdir -p /models

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MODELS_DIR=/models
ENV MONGODB_HOST=${MONGODB_HOST:-mongodb://localhost:27017}
ENV MONGODB_DATABASE=${MONGODB_DATABASE:-chatbot}

# Health check for API services
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default entrypoint: dialogue manager service
# Override with SERVICE environment variable for other services
CMD ["sh", "-c", "if [ \"$SERVICE\" = \"admin-training-api\" ]; then uvicorn app.main:app --host 0.0.0.0 --port 8000; elif [ \"$SERVICE\" = \"training-worker\" ]; then python -m app.bot.nlu.pipeline_utils train; elif [ \"$SERVICE\" = \"fastapi-backend\" ]; then uvicorn app.main:app --host 0.0.0.0 --port 8000; else uvicorn app.bot.dialogue_manager.api:app --host 0.0.0.0 --port 8000; fi"]