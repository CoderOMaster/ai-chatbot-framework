### Multi-stage Dockerfile for smaller final image

# Stage 1: Build stage with dependencies
FROM python:3.11-slim AS builder
ARG PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies for spaCy C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --upgrade pip wheel
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# Stage 2: Final image
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1

# Install runtime OS deps for spaCy if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy wheels from builder
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY . /app

# Optionally, if you want to pre-download a spaCy model during image build,
# you can uncomment the following lines and set MODEL_NAME arg at build-time.
# ARG MODEL_NAME=en_core_web_sm
# RUN python -m spacy download ${MODEL_NAME}

# Expose port
ENV PORT=8000
EXPOSE 8000

# Health check for container
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["/bin/sh", "-c", 'wget -qO- http://localhost:8000/health | grep -q \"ok\" || exit 1']

# Entrypoint
CMD ["uvicorn", "app.__init__:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
