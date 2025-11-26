FROM ollama/ollama:latest

# Install bash for script execution
RUN apt-get update && apt-get install -y bash && rm -rf /var/lib/apt/lists/*

# Copy the entrypoint script
COPY entrypoint.sh /scripts/entrypoint.sh
RUN chmod +x /scripts/entrypoint.sh

# Set default model (can be overridden at runtime)
ENV MODEL_NAME=llama2

# Expose Ollama API port
EXPOSE 11434

# Health check to verify Ollama is running
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD /bin/ollama list || exit 1

# Set the entrypoint
ENTRYPOINT ["/scripts/entrypoint.sh"]