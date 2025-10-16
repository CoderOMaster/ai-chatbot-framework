FROM python:3.11-slim AS base

# Install system dependencies required for asyncpg and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home appuser
WORKDIR /home/appuser

FROM base AS builder
ENV PIP_NO_CACHE_DIR=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /tmp/wheels -r /tmp/requirements.txt

FROM base AS final
COPY --from=builder /tmp/wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /home/appuser/app
WORKDIR /home/appuser/app
RUN chown -R appuser:appuser /home/appuser
USER appuser

# Runtime environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Use Gunicorn with Uvicorn workers for production
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "__init__:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--log-level", "info"]
