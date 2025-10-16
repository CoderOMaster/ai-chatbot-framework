FROM python:3.11-slim AS base

# Install build deps for some wheels and certificates
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install runtime deps in a separate layer
FROM base AS deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
FROM base AS final
# Create an unprivileged user
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY . /app

# Ensure non-root
USER appuser

# Expose port
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
EXPOSE 8000

# Use uvicorn with standard loop for production
CMD ["uvicorn", "memory_saver_mongo:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "uvloop", "--log-level", "info"]
