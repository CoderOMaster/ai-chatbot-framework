### Multi-stage Dockerfile for an optimized FastAPI image

# Build stage
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements to cache dependencies
COPY requirements.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Final stage
FROM python:3.11-slim
WORKDIR /app
ENV PATH=/app/.local/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/* \
    && rm -rf /wheels

# Copy application code
COPY . /app

# Service port
EXPOSE 8000

# Recommended to run as non-root in containers
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Entrypoint (uvicorn with sensible defaults)
CMD ["uvicorn", "app.bot.channels.facebook.routes:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
