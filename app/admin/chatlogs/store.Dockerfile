FROM python:3.10-slim as build

# Install build deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install runtime dependencies into a venv
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Application stage
FROM python:3.10-slim

ENV PATH="/opt/venv/bin:$PATH"

# Copy venv from build stage
COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY . /app

# Create a non-root user
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Use uvicorn for async server. In Kubernetes use readiness/liveness probes to control lifecycle.
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio", "--limit-max-keep-alive", "5"]
