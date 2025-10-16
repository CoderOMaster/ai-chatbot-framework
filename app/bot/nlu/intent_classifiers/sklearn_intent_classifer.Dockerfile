### Multi-stage Dockerfile optimized for runtime size and reproducible builds

# 1) Build stage: install build deps if needed for any packages (scikit-learn, numpy)
FROM python:3.10-slim AS build

# Install build tools only in build stage (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Copy only requirements to leverage Docker cache
COPY requirements.txt .

# Install into a wheelhouse to later copy only installed packages
RUN python -m pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# 2) Final runtime image
FROM python:3.10-slim

# runtime deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy wheels and install
COPY --from=build /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY sklearn_intent_classifer.py /app/sklearn_intent_classifer.py
COPY requirements.txt /app/requirements.txt

# Create directories for models and logs
RUN mkdir -p /app/models /app/logs

# Expose application port
ENV PORT=8000
EXPOSE ${PORT}

# Configure default env vars; override at runtime with kubernetes/ecs
ENV MODEL_DIR=/app/models
ENV MODEL_NAME=sklearn_intent_model.hd5
ENV SPACY_MODEL=en_core_web_md
ENV LOG_LEVEL=INFO
ENV METRICS_PATH=/metrics

# Use a non-root user
RUN useradd -m appuser || true
USER appuser

CMD ["/usr/local/bin/python", "-u", "sklearn_intent_classifer.py"]
