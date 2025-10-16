# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/memory/models.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 16

## Breaking Changes
- models.py was refactored and packaged into an HTTP microservice. The original module-level State class behavior is preserved but now lives inside the service code and includes additional helper methods for (de)serialization.
- to_dict now serializes the date as ISO string and guards user_message serialization. If your callers relied on the previous exact structure or raw datetime object, adjust consumers accordingly.
- from_dict now attempts to coerce a user_message into the UserMessage class if possible; passing arbitrary structures may not be rehydrated exactly as before.
- Persistent storage: states are now persisted into a SQL table named 'states'. Existing external storage expectations must be migrated.
- Side effect: The service introduces new environment variables (DB_URL, DB_POOL_SIZE, METRICS_ENABLED, LOG_LEVEL). Ensure they are set in deployment.
- The application now requires additional runtime dependencies (FastAPI, Uvicorn, SQLAlchemy, prometheus-client). Make sure to include them in your deployment image.

## Migration Steps
1. Build and test the application locally:
   - Ensure your project package (app.bot.dialogue_manager.models) is available in the container build context.
   - Update DB_URL environment variable depending on target: for production use a managed RDS/Cloud SQL/managed DB; the example defaults to sqlite for simplicity.
   - Run locally: python -m uvicorn app:app --host 0.0.0.0 --port 8000

2. Containerize and push image:
   - docker build -t <registry>/state-service:latest .
   - docker push <registry>/state-service:latest

3. Deploy to Kubernetes (example):
   - kubectl apply -f k8s_manifest.yaml
   - Ensure DB_URL is set via a Secret or ConfigMap referencing your managed DB endpoint and credentials.

4. Readiness/Liveness:
   - /health responds quickly for liveness checks.
   - /readiness checks DB connectivity; adjust READINESS_TIMEOUT/behavior if using eventual databases like DynamoDB or if latency is expected.

5. Observability:
   - Logs are emitted as structured JSON.
   - Metrics are available at /metrics when METRICS_ENABLED=true and can be scraped by Prometheus.

6. Graceful shutdown:
   - The service listens for SIGTERM/SIGINT, disposes DB connection pool, and sets a shutdown event allowing the platform to drain connections.

7. DB pooling:
   - SQLAlchemy engine is configured with pool_size and max_overflow; change DB_POOL_SIZE env var to tune pool in production.

8. Secrets:
   - Do not store DB credentials directly in manifests. Use Kubernetes Secrets or your cloud secret manager.

