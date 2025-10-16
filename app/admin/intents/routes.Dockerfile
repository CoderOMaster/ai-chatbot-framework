### Multi-stage Dockerfile for Python FastAPI app

# ----- Build stage -----
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first for better caching
COPY requirements.txt /app/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /app/requirements.txt

# ----- Final stage -----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy wheels and install
COPY --from=builder /wheels /wheels
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /app

# chown
RUN chown -R appuser:appgroup /app
USER appuser

# Uvicorn opts: use multiple workers in production via gunicorn if needed
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# Start the app via Uvicorn (for K8s/ECS it's recommended to set workers through gunicorn + uvicorn workers)
CMD ["uvicorn", "routes:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "0", "--loop", "uvloop", "--http", "h11"]
