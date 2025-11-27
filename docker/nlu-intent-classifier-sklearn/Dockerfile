# Multi-stage build for nlu-intent-classifier-sklearn microservice
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Create wheels for dependencies
RUN pip install --user --no-cache-dir --wheel --no-deps --wheel-dir /build/wheels \
    scikit-learn==1.3.2 \
    numpy==1.24.3 \
    scipy==1.11.2 \
    cloudpickle==2.0.0 \
    flask==2.3.3 \
    gunicorn==21.2.0 \
    pydantic==2.3.0

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder
COPY --from=builder /build/wheels /wheels

# Install wheels
RUN pip install --user --no-cache-dir --no-index --find-links /wheels \
    scikit-learn \
    numpy \
    scipy \
    cloudpickle \
    flask \
    gunicorn \
    pydantic

# Copy application code
COPY app/ /app/app/
COPY config/ /app/config/

# Create model storage directory
RUN mkdir -p /models && chmod 755 /models

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    MODEL_PATH=/models \
    N_JOBS=-1 \
    FLASK_APP=app.bot.nlu.intent_classifiers.api \
    WORKERS=4 \
    THREADS=2 \
    TIMEOUT=60

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health', timeout=5)" || exit 1

# Expose REST API port
EXPOSE 5000

# Volume for model storage
VOLUME ["/models"]

# Run gunicorn with multiple workers for CPU-bound inference
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "4", \
     "--threads", "2", \
     "--worker-class", "gthread", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.bot.nlu.intent_classifiers.api:create_app()"]