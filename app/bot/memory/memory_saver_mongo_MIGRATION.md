# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/memory/memory_saver_mongo.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 6

## Breaking Changes
- Added an HTTP API surface: existing code was a library; now there's a FastAPI service exposing endpoints (/state/{thread_id}, /state/{thread_id}/all).
- Environment variables are required/used: MONGODB_URI, DB_NAME, COLLECTION_NAME, and optional pooling variables (MONGO_MAX_POOL_SIZE, MONGO_MIN_POOL_SIZE). Provide them in deployment.
- The service now expects JSON payloads for saving state that must be compatible with app.bot.memory.models.State.from_dict. If previous callers used direct MemorySaverMongo.save(State) invocations, they should switch to HTTP client or reuse the MemorySaverMongo class directly.
- Logging format changed to structured JSON. Consumers of plain-text logs need to adapt.
- Prometheus metrics exposed at /metrics; metric names and labels added (api_requests_total, api_request_duration_seconds).
- Graceful shutdown handling added; process termination may cancel in-flight tasks — ensure clients handle retries if needed.

## Migration Steps
1) Build image
   - docker build -t <registry>/memory-saver-mongo:latest .
2) Push
   - docker push <registry>/memory-saver-mongo:latest
3) Create Kubernetes secrets (for MONGODB_URI):
   - kubectl create secret generic mongo-credentials --from-literal=uri='mongodb://user:pass@mongo-host:27017/?authSource=admin'
4) Apply manifests
   - kubectl apply -f k8s-manifest.yaml
5) Configure scaling / HPA, logging centralization (e.g., Fluentd), and monitoring (Prometheus scraping /metrics)
6) For AWS ECS/Fargate: push image to ECR, create task definition and service with environment variables pointing to secrets (via AWS Secrets Manager)
7) Validate readiness/liveness endpoints and check logs for structured JSON entries
8) If TLS is required for MongoDB, ensure root CA is present in the container base image or use OS trust store (python:slim usually includes it). Set MONGODB_URI with tls=true and provide CA via mounted secret if needed.

Notes on zero-downtime deploys:
- Use rolling updates in Kubernetes (default) and ensure readiness probe passes before replacing pods.
- In ECS, configure minimum healthy percent and maximum percent appropriately.

