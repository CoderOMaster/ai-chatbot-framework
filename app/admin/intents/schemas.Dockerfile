### Multi-stage optimized Dockerfile

# ----- Builder: build wheels -----
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /wheels

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# Build wheels to /wheels
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ----- Final image -----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Install runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder
COPY --from=builder /wheels /wheels
# Install from wheels
RUN pip install --no-cache-dir /wheels/*

# Copy app
COPY app ./app
COPY requirements.txt ./requirements.txt

# Non-root user (recommended in containers)
RUN groupadd -r appuser && useradd -r -g appuser appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Use Uvicorn with Gunicorn for production-grade process management
ENV PORT=8000
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "-b", "0.0.0.0:8000", "app.main:app"]
