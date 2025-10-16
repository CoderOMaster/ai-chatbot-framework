### Multi-stage optimized Dockerfile for the FastAPI microservice

# Builder stage (install wheels and compile dependencies if needed)
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install into a directory for later copy
COPY requirements.txt ./
RUN pip --no-cache-dir wheel --wheel-dir=/wheels -r requirements.txt

# Final stage
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy wheels from builder and install
COPY --from=builder /wheels /wheels
RUN pip --no-cache-dir install --no-deps /wheels/* \
    && rm -rf /wheels

# Copy application
COPY . /app

# Recommended non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Use an ASGI server (gunicorn + uvicorn workers) in production; allow override with CMD
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "store:app", "-b", "0.0.0.0:8000", "--workers", "4", "--log-level", "info"]
