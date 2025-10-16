FROM python:3.11-slim AS builder

# Install build deps for some wheels if needed
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Install pip packages into target image via a wheel cache (faster rebuilds)
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 ca-certificates && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application
COPY . /home/appuser/app
RUN chown -R appuser:appuser /home/appuser/app
USER appuser
WORKDIR /home/appuser/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Use a production-grade ASGI server: uvicorn with multiple workers can be orchestrated by Kubernetes
CMD ["uvicorn", "routes:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
