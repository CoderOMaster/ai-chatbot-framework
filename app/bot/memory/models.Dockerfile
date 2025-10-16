FROM python:3.10-slim AS base

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install first (leverages Docker cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app

# Use a non-root user for better security
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000
EXPOSE 8000

# Default command runs uvicorn on the FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
