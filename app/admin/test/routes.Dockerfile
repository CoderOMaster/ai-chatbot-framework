######### Builder stage #########
FROM python:3.10-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements & install
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels -r requirements.txt

######### Final stage #########
FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# system deps for runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# copy wheels and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# copy app
COPY . /app

# expose port
EXPOSE 8000

# uvicorn recommended command with graceful shutdown support
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
