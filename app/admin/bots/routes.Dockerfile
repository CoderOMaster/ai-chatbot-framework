### Multi-stage Dockerfile for an optimized FastAPI microservice

# ---- Build stage ----
FROM python:3.10-slim AS build

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pip-tools optionally, copy requirements and install
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# ---- Final stage ----
FROM python:3.10-slim

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser

# Copy installed packages from build stage
COPY --from=build /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

# Copy application code
COPY . /home/appuser/app
WORKDIR /home/appuser/app

# Ensure we run as non-root
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000

EXPOSE 8000

# Use Uvicorn with a single worker by default; in Kubernetes/GKE use K8s to scale replicas
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "${PORT}", "--proxy-headers"]
