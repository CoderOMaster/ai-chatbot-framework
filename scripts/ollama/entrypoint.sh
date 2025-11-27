#!/bin/bash
set -euo pipefail

# Configuration
MODEL_NAME="${MODEL_NAME:-llama2}"
OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
HEALTH_CHECK_TIMEOUT=300
HEALTH_CHECK_INTERVAL=5
MAX_RETRIES=3
RETRY_DELAY=10

# Logging
log_info() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ℹ️  $*"
}

log_success() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✅ $*"
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ❌ $*" >&2
}

log_warning() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  $*"
}

# Graceful shutdown handler
cleanup() {
    log_info "Shutting down Ollama gracefully..."
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 5
        if kill -0 "$pid" 2>/dev/null; then
            log_warning "Force killing Ollama process..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    log_success "Ollama shutdown complete"
    exit 0
}

trap cleanup SIGTERM SIGINT EXIT

# Health check function
health_check() {
    local elapsed=0
    log_info "Waiting for Ollama to be ready (timeout: ${HEALTH_CHECK_TIMEOUT}s)..."
    
    while [ $elapsed -lt $HEALTH_CHECK_TIMEOUT ]; do
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            log_success "Ollama is healthy"
            return 0
        fi
        sleep $HEALTH_CHECK_INTERVAL
        elapsed=$((elapsed + HEALTH_CHECK_INTERVAL))
    done
    
    log_error "Ollama health check failed after ${HEALTH_CHECK_TIMEOUT}s"
    return 1
}

# Memory monitoring function
monitor_memory() {
    local model_name="$1"
    local memory_usage
    
    memory_usage=$(curl -sf http://localhost:11434/api/show -d "{\"name\":\"$model_name\"}" 2>/dev/null | grep -o '"memory":[0-9]*' | cut -d':' -f2 || echo "unknown")
    
    if [ "$memory_usage" != "unknown" ]; then
        local memory_gb=$((memory_usage / 1024 / 1024 / 1024))
        log_info "Model '$model_name' memory usage: ${memory_gb}GB"
        
        if [ "$memory_gb" -gt 14 ]; then
            log_warning "High memory usage detected: ${memory_gb}GB (threshold: 14GB)"
        fi
    fi
}

# Model download with retry logic
download_model() {
    local model="$1"
    local attempt=1
    
    log_info "Retrieving model: $model (attempt $attempt/$MAX_RETRIES)..."
    
    while [ $attempt -le $MAX_RETRIES ]; do
        if ollama pull "$model"; then
            log_success "Model '$model' downloaded successfully"
            return 0
        fi
        
        if [ $attempt -lt $MAX_RETRIES ]; then
            log_warning "Model download failed. Retrying in ${RETRY_DELAY}s... (attempt $((attempt + 1))/$MAX_RETRIES)"
            sleep $RETRY_DELAY
        fi
        attempt=$((attempt + 1))
    done
    
    log_error "Failed to download model '$model' after $MAX_RETRIES attempts"
    return 1
}

# Verify model exists locally
verify_model() {
    local model="$1"
    
    if ollama list | grep -q "^$model"; then
        log_success "Model '$model' verified in local cache"
        return 0
    fi
    
    log_error "Model '$model' not found in local cache"
    return 1
}

# Main execution
main() {
    log_info "Starting Ollama service..."
    log_info "Configuration: MODEL_NAME=$MODEL_NAME, OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL"
    
    # Start Ollama in background
    export OLLAMA_NUM_PARALLEL
    /bin/ollama serve &
    pid=$!
    log_info "Ollama process started (PID: $pid)"
    
    # Wait for Ollama to be healthy
    if ! health_check; then
        log_error "Ollama failed to start"
        exit 1
    fi
    
    # Download model with retry logic
    if ! download_model "$MODEL_NAME"; then
        log_error "Failed to download model, exiting"
        exit 1
    fi
    
    # Verify model was downloaded
    if ! verify_model "$MODEL_NAME"; then
        log_error "Model verification failed"
        exit 1
    fi
    
    # Initial memory check
    monitor_memory "$MODEL_NAME"
    
    log_success "Ollama is ready and model '$MODEL_NAME' is loaded"
    
    # Wait for process
    wait $pid
}

main "$@"