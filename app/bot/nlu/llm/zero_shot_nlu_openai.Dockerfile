FROM python:3.11-slim AS builder

# Install build deps for some packages (psycopg2, cryptography)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /app

# Use non-root user
RUN useradd -ms /bin/bash appuser && chown -R appuser /app
USER appuser

ENV PORT=8000
EXPOSE 8000

# Health check path used by k8s
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s CMD ["/bin/sh", "-c", "curl -f http://localhost:${PORT}/health || exit 1"]

CMD ["uvicorn", "zero_shot_nlu_service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
