### Multi-stage Dockerfile for production
# Stage 1 - build
FROM python:3.11-slim as builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip
RUN pip wheel --no-deps --wheel-dir /wheels -r requirements.txt

# Stage 2 - runtime
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /wheels/requirements.txt || true
# In case the above fails (some pip versions), just install from requirements
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . /app

# Non-root user
RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "__main__:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio"]
