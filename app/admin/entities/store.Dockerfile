FROM python:3.11-slim AS builder

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies in a virtualenv to reduce final image size
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels -r /app/requirements.txt

FROM python:3.11-slim AS runtime

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -r -u 1000 -g appuser appuser

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy wheels and install
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /app/requirements.txt && rm -rf /wheels

# Copy application
COPY . /app

# Use non-root user
USER appuser

EXPOSE 8000

ENV SERVICE_HOST=0.0.0.0
ENV SERVICE_PORT=8000

CMD ["uvicorn", "store:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
