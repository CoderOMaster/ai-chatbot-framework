#!/bin/bash

set -euo pipefail

# Validate that MODEL_NAME is set
if [[ -z "${MODEL_NAME:-}" ]]; then
    echo "❌ Error: MODEL_NAME environment variable is not set" >&2
    exit 1
fi

# Start Ollama in the background
echo "🔵 Starting Ollama server..."
if ! /bin/ollama serve &
then
    echo "❌ Error: Failed to start Ollama server" >&2
    exit 1
fi

# Record Process ID
pid=$!

# Healthcheck loop: wait for Ollama to be ready
echo "🔵 Waiting for Ollama server to be ready..."
max_attempts=30
attempt=0
while [[ $attempt -lt $max_attempts ]]; do
    if /bin/ollama list &>/dev/null; then
        echo "🟢 Ollama server is ready"
        break
    fi
    attempt=$((attempt + 1))
    if [[ $attempt -eq $max_attempts ]]; then
        echo "❌ Error: Ollama server failed to become ready after ${max_attempts} attempts" >&2
        kill $pid 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Pull the specified model
echo "🔵 Retrieving model: $MODEL_NAME..."
if ! /bin/ollama pull "$MODEL_NAME"; then
    echo "❌ Error: Failed to pull model $MODEL_NAME" >&2
    kill $pid 2>/dev/null || true
    exit 1
fi
echo "🟢 Model $MODEL_NAME loaded successfully"

# Wait for Ollama process to finish
wait $pid