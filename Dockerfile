FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    motor \
    pydantic \
    pydantic-settings \
    uvicorn \
    fastapi

# Copy application files
COPY app/database.py app/
COPY app/config.py app/
COPY app/config_loader.py app/
COPY app/admin/bots/store.py app/admin/bots/
COPY app/admin/bots/schemas.py app/admin/bots/
COPY app/admin/entities/store.py app/admin/entities/
COPY app/admin/intents/store.py app/admin/intents/
COPY app/admin/integration/store.py app/admin/integration/

# Create __init__.py files for packages
RUN touch app/__init__.py \
    && touch app/admin/__init__.py \
    && touch app/admin/bots/__init__.py \
    && touch app/admin/entities/__init__.py \
    && touch app/admin/intents/__init__.py \
    && touch app/admin/integration/__init__.py

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MONGODB_HOST=${MONGODB_HOST:-mongodb://localhost:27017}
ENV MONGODB_DATABASE=${MONGODB_DATABASE:-admin}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import asyncio; from app.database import get_database_client; asyncio.run(get_database_client().health_check())" || exit 1

# Run the application
CMD ["uvicorn", "app.admin.api:app", "--host", "0.0.0.0", "--port", "8000"]