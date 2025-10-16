FROM python:3.10-slim as builder

# Install build dependencies (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install runtime dependencies into a venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only requirements first for better caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Final image
FROM python:3.10-slim
ENV PATH="/opt/venv/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --from=builder /app /app

# Non-root user (optional)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser || true
USER appuser

EXPOSE 8000
ENV SERVICE_HOST=0.0.0.0
ENV SERVICE_PORT=8000

CMD ["uvicorn", "__main__:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
