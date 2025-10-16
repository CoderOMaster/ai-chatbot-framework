FROM python:3.10-slim AS build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and create wheels in build stage for faster installs
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# Final runtime image
FROM python:3.10-slim

# Create a non-root user
RUN useradd --create-home appuser
WORKDIR /app

# Install runtime dependencies from wheels
COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /app/requirements.txt \
    && rm -rf /wheels

# Copy application code
COPY . /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Use non-root user
USER appuser

EXPOSE 8000

# Default command to run the app with uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
