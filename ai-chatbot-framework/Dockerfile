# Core API service Dockerfile
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (optional): build tools if any compiled deps are present
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY ai-chatbot-framework/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
# Copy only what we need to run the service
COPY app/ /app/app/
COPY ai_chatbot_common/ /app/ai_chatbot_common/
COPY nlu_service/ /app/nlu_service/
COPY app/static/ /app/app/static/

EXPOSE 8000

# Start using gunicorn with uvicorn workers
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "-b", "0.0.0.0:8000", "--workers", "2"]