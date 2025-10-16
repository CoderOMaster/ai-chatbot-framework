########################################
# Builder stage - create wheelhouse
########################################
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build deps (kept minimal - psycopg2-binary avoids heavy build deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
# Build wheels to speed up later install and provide reproducible builds
RUN python -m pip install --upgrade pip wheel && \
    pip wheel --wheel-dir=/wheels -r requirements.txt

########################################
# Final stage
########################################
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create a non-root user
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

# Install runtime deps
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy app
COPY . /app
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Best practice: set PORT via env var
ENV PORT=8000

# Use uvicorn with a sensible default; override cmd in k8s or ECS task
CMD ["uvicorn", "__init__:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "uvloop"]
