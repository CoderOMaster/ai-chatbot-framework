### Multi-stage optimized Dockerfile
# Stage 1: build
FROM python:3.11-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first to leverage cache
COPY requirements.txt ./
RUN pip install --upgrade pip && pip wheel --no-deps --wheel-dir /wheels -r requirements.txt

# Stage 2: runtime
FROM python:3.11-slim
RUN addgroup --system app && adduser --system --group app
WORKDIR /home/app

COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /wheels/requirements.txt || true
# If the above is not used, fallback pip install
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /home/app

# Ensure non-root
USER app

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV LOG_LEVEL=INFO

EXPOSE 8000

# Entrypoint
CMD ["uvicorn", "dialogue_manager_service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
