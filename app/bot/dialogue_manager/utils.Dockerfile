### Multi-stage Dockerfile for production

# Build stage (if you needed to compile or collect assets - keep minimal here)
FROM python:3.10-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build deps (if any) and pip-tools can be added here if desired
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements to leverage Docker layer caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# Final image
FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app.py ./app.py

# Create non-root user
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Entrypoint
ENV PORT=8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
