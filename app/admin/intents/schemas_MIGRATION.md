# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/intents/schemas.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 8

## Breaking Changes
- Schemas now expect ObjectIdField to serialize as a string. If previously you used BSON ObjectId objects directly in the code that relied on native ObjectId types, you must adapt to receive/convert string IDs.
- Pydantic version updated to v2.x patterns (ConfigDict/model_config used). If your project uses Pydantic v1.x with FastAPI older compatibility, adjust versions or the models.
- The database connection is now pooled and managed at process level. Any code that previously created/destroyed Mongo connections per request should be updated to use the shared client (app.state.db or via provided helper).
- Logging format changed to JSON. Downstream consumers expecting plain text logs must be updated.
- Application now exposes /health, /readiness and /metrics endpoints and a simple CRUD example (/intents). Ensure external load balancers and probes are updated accordingly.

## Migration Steps
1) Project structure
   - New files added: app/main.py (FastAPI app), app/database.py (Mongo client wrapper and helper), app/logging_config.py, app/schemas.py (refactored). Ensure the 'app' package is included in the container image.

2) Environment variables
   - MONGO_URI (default: mongodb://localhost:27017)
   - MONGO_DB (default: mydb)
   - MONGO_MAX_POOL (default: 50)
   - LOG_LEVEL (default: INFO)
   - SERVICE_NAME (default: intent-service)
   - PORT (default: 8000)

   Set these in your Kubernetes Deployment / ECS Task Definition.

3) Health & readiness
   - /health (liveness): fast check that the process is alive.
   - /readiness: checks MongoDB connectivity with a ping; returns 503 if DB unreachable.
   Configure these as Kubernetes probes.

4) Logging
   - Structured JSON logging using python-json-logger. Logs are emitted to stdout for integration with cluster log collectors.

5) DB Connection Pooling
   - MongoClient is created once per process with maxPoolSize configured via MONGO_MAX_POOL.

6) Graceful Shutdown
   - FastAPI lifespan context creates/tears down the MongoClient. Signal handlers set a shutdown event so in-process tasks can react. Uvicorn/Gunicorn handle process lifecycle; our lifespan ensures resources are closed.

7) Prometheus Metrics
   - Basic request counter provided and exposed at /metrics. For production, configure scraping in Prometheus.

8) Build & deploy
   - Build the Docker image using the provided Dockerfile and push to your registry.
   - Update the image in the Kubernetes manifest and apply.


