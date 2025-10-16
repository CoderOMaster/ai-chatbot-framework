# Multi-stage Dockerfile for a small, efficient container

# 1) Builder stage - build wheel and install dependencies
FROM python:3.11-slim AS build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements to leverage Docker layer caching
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# 2) Final stage - runtime
FROM python:3.11-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install runtime dependencies from wheels
COPY --from=build /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /app

# Ensure non-root user owns the app directory
RUN chown -R appuser:appgroup /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health/probe port and app port
EXPOSE 8000

# Recommended production command (overrideable in k8s manifests)
CMD ["uvicorn", "routes:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
