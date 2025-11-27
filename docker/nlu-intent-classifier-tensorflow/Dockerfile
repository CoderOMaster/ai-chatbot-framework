# TensorFlow Intent Classifier Microservice
# Supports both GPU and CPU inference
# Base: tensorflow/tensorflow:2.14.0 with optional GPU support

ARG TF_VERSION=2.14.0
ARG CUDA_VARIANT=gpu

FROM tensorflow/tensorflow:${TF_VERSION}-${CUDA_VARIANT}

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install spacy model
RUN python -m spacy download en_core_web_md

# Copy application code
COPY app/ /app/app/

# Create model storage directory
RUN mkdir -p /models

# Expose ports
# 5000: Flask API
# 8500: TensorFlow Serving gRPC
# 8501: TensorFlow Serving REST
EXPOSE 5000 8500 8501

# Environment variables
ENV MODEL_PATH=/models
ENV TF_ENABLE_ONEDNN_OPTS=1
ENV CUDA_VISIBLE_DEVICES=0
ENV TF_CPP_MIN_LOG_LEVEL=2
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run application
CMD ["python", "-m", "app.bot.nlu.intent_classifiers.server"]