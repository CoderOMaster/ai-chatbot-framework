### Multi-stage Dockerfile for production
# Build stage (cache dependencies)
FROM python:3.11-slim AS builder

# Install build deps for any compiled wheels (if needed)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --prefix=/install -r requirements.txt

# Final stage: small runtime image
FROM python:3.11-slim

RUN addgroup --system appgroup && adduser --system --ingroup appgroup --no-create-home appuser

ENV PATH="/usr/local/bin:$PATH"

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
WORKDIR /app
COPY . /app

# Ensure non-root
USER appuser

EXPOSE 8000

# Use env vars for host/port, but default to 0.0.0.0:8000
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "-"]
