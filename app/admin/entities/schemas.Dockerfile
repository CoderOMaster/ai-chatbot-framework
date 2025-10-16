### Multi-stage optimized Dockerfile for small image size and security

# --- Build stage (optional for compiled dependencies) ---
FROM python:3.11-slim as builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --upgrade pip && pip wheel --no-deps --wheel-dir /wheels -r requirements.txt

# --- Final runtime image ---
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser -m appuser

WORKDIR /app

# Install runtime deps from wheels
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache /wheels/* && pip install --no-cache -r requirements.txt

# Copy app code
COPY . /app
RUN chown -R appuser:appuser /app
USER appuser

ENV LISTEN_PORT=8000
EXPOSE 8000

# Recommended to run with an external process manager in production (uvicorn/gunicorn)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
