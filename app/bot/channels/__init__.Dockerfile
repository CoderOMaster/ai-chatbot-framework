### Multi-stage Dockerfile for optimized image

# 1) Builder stage: build wheels for faster installs
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt ./
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# 2) Final image
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install runtime deps (libpq for postgres connectivity)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /app

# Use a non-root user for security
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# By default we recommend using Gunicorn + Uvicorn workers for production
# The module path assumes package name 'app' and FastAPI instance 'app' in __init__.py
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--log-level", "info"]
