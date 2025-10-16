#############################
# Multi-stage Dockerfile
#############################

# Builder stage: install wheels and compile dependencies if needed
FROM python:3.11-slim AS builder
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install build deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest and install into /install
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel
RUN python -m pip wheel --wheel-dir=/wheels -r requirements.txt

# Final runtime image
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Create non-root user
RUN groupadd -r app && useradd -r -g app app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels "*"

# Copy application
COPY . /app
RUN chown -R app:app /app
USER app

EXPOSE 8000

# Use environment variable to pick production server if needed
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "${WORKERS:-1}"]
