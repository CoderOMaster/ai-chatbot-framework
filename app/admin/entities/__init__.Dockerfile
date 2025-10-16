### Multi-stage Dockerfile for building and running the FastAPI microservice

# --- Builder stage: install dependencies into a slim image ---
FROM python:3.9-slim AS builder

# Install OS packages required by common Python packages (adjust if your project needs more)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first for better caching
COPY requirements.txt ./requirements.txt
RUN pip --disable-pip-version-check --no-cache-dir install -r requirements.txt -t /install

# --- Final image: smaller, only runtime artifacts ---
FROM python:3.9-slim

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser || true
WORKDIR /app

# Copy installed packages
COPY --from=builder /install /usr/local/lib/python3.9/site-packages

# Copy application code
# The project convention: this package is named 'app' and this file is app/__init__.py
COPY app /app/app

# Expose port
ENV PORT=8000
EXPOSE ${PORT}

# Use a non-root user
USER appuser

# Uvicorn is used to serve the FastAPI application. Adjust --workers to your needs using env var.
CMD ["/usr/local/bin/uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "30"]
