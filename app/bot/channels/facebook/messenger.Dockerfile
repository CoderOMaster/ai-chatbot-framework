FROM python:3.10-slim AS builder

# Install build deps and install into wheelhouse
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application
COPY . /app

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "messenger_service:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--loop", "uvloop", "--workers", "1"]
