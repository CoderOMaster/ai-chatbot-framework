# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/dialogue_manager/dialogue_manager.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 24

## Breaking Changes
- The original dialogue_manager.py was converted into an ASGI microservice using FastAPI; entrypoints and initialization are different: usage moves from direct instantiation to HTTP endpoints (/process, /health, /readiness).
- The module now expects environment variables (MONGO_URI, MONGO_MAX_POOL_SIZE, LOG_LEVEL, SERVE_METRICS, WORKERS). If your prior runtime populated app.database.client differently, provide MONGO_URI or ensure app.database.client is available.
- Logging format changed to structured JSON. Consumers parsing plaintext logs must adapt.
- Startup becomes asynchronous and will try to initialize NLU pipeline and load intents at startup; any prior code that expected lazy initialization may need adjustment.
- Docker entrypoint and execution are now via uvicorn; if you previously imported the module directly, use the new HTTP endpoints instead.
- State serialization relies on State.to_dict(); ensure that method exists and returns JSON-serializable structures. If prior consumers used a different representation, they must adapt to the REST contract.

## Migration Steps
Deployment steps and notes:

1. Build image
   - Ensure the Python dependencies (requirements.txt) match your project requirements.
   - Build and push the container image to your registry: docker build -t <registry>/dialogue-manager:latest . && docker push <registry>/dialogue-manager:latest

2. Store secrets
   - Put MONGO_URI into Kubernetes Secret (mongo-creds) or AWS Secrets Manager for Fargate/ECS.

3. Deploy to Kubernetes
   - kubectl apply -f k8s_manifest.yaml (replace image and secret values).
   - Ensure the cluster nodes have necessary system-level libraries for ML dependencies if needed.

4. Readiness and liveness
   - /health is lightweight and always returns OK if the process is running.
   - /readiness checks NLU pipeline and DB connectivity; ensure model artifacts are available on startup.

5. Scaling
   - The service is horizontally scalable. Ensure your NLU pipeline/models are load-friendly (either shared read-only model files or lazy-loaded per-process).
   - Set WORKERS env var if running with uvicorn multiple workers; in Kubernetes prefer multiple replicas instead of many workers.

6. Connection pooling
   - MongoDB client uses maxPoolSize from MONGO_MAX_POOL_SIZE to control pool size. Tune per replica so the DB can handle total connections.

7. Logging
   - Structured JSON logs are emitted to stdout to be consumed by logging/observability stack (Fluentd/FireLens).

8. Metrics
   - /metrics endpoint is available when SERVE_METRICS=true. Configure Prometheus scrape accordingly.

9. Graceful shutdown
   - SIGTERM is handled; the app attempts to close DB client on shutdown. Uvicorn also handles graceful shutdowns by default.

