FROM python:3.11-slim AS builder

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

FROM python:3.11-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-index /wheels/* && \
    rm -rf /wheels

# Copy application code
COPY . /app
RUN chown -R appuser:appgroup /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

# Use a production-ready command in runtime. In k8s/ECS we recommend using a process manager
# or run via an entrypoint. Keep single worker here for container; scale by replicas.
CMD ["uvicorn", "app.routes:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop"]
