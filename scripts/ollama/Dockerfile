FROM ollama/ollama:latest

# Set environment variables
ENV MODEL_NAME=llama2 \
    OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_HOST=0.0.0.0:11434

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create model cache directory with proper permissions
RUN mkdir -p /root/.ollama/models && \
    chmod -R 755 /root/.ollama

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:11434/api/tags || exit 1

# Expose Ollama API port
EXPOSE 11434

# Volume for model cache persistence
VOLUME ["/root/.ollama/models"]

# Run entrypoint script
ENTRYPOINT ["/entrypoint.sh"]