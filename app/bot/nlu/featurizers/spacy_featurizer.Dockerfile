#########################
# Multi-stage Dockerfile
#########################

# Builder stage: install build deps and wheel packages if needed
FROM python:3.10-slim as builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install build-time packages needed by spaCy & psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential git curl ca-certificates libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (leverage Docker cache)
COPY requirements.txt /app/requirements.txt

# Install into builder environment
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r /app/requirements.txt


# Final stage: smaller runtime image
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# OS packages still needed at runtime for spaCy wheels (C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy wheels from builder and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /app

# If you want to install the spaCy model into the image, uncomment the next line or install in CI
# RUN python -m spacy download en_core_web_sm

# Expose port
EXPOSE 8000

# Default command: run with Uvicorn
CMD ["uvicorn", "spacy_featurizer_service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
