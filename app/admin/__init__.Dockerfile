### Multi-stage optimized Dockerfile

# Stage 1: builder
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Copy only requirements first for better caching
COPY requirements.txt ./
RUN pip --disable-pip-version-check install --upgrade pip
RUN pip --no-cache-dir install -r requirements.txt

# Stage 2: final image
FROM python:3.11-slim

# Create non-root user (optional but recommended)
RUN groupadd -r app && useradd --no-log-init -r -g app app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code (we expect package named 'app' with __init__.py)
COPY app /app/app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000

# Expose port
EXPOSE 8000

# Use a non-privileged user
USER app

# Entrypoint
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--loop", "uvloop", "--http", "h11"]
