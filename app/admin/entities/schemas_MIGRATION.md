# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/entities/schemas.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 4

## Breaking Changes
- Provided a small app.database implementation (ObjectIdField, client helpers). If your repository already contains app.database, merge or remove duplicates.
- Schemas kept but models now live under app/schemas.py and are used by the FastAPI endpoints. Import paths changed to app.schemas.Entity if you used relative imports.
- Entity.id field uses ObjectIdField (custom pydantic type). When creating entities, the API expects JSON without an explicit id (server will create one).
- The microservice now depends on motor (async MongoDB driver). If previously synchronous DB drivers were used, review and adapt app.database to match your driver.
- Startup/shutdown behavior: application sets up a global Motor client and closes it on shutdown; ensure other parts of your app use get_mongo_client/get_database to share the same client.
- Logging format changed to structured JSON by default; change LOG_JSON or LOG_LEVEL env vars to alter behavior.

## Migration Steps
1) Build and push the container image:
   - docker build -t <registry>/entities-service:latest .
   - docker push <registry>/entities-service:latest

2) Update Kubernetes manifest with your image registry and apply:
   - kubectl apply -f k8s-manifest.yaml

3) Ensure environment variables (MONGO_URI, MONGO_DB) point to your MongoDB service.

4) If deploying to AWS ECS via Terraform:
   - Build & push to ECR, update the task definition image, then terraform apply.

5) Probes:
   - K8s liveness: /health
   - K8s readiness: /readiness

6) Logging & metrics:
   - Logs are JSON structured to stdout; configure your cluster log collector (Fluentd/CloudWatch).
   - Prometheus can scrape /metrics from the service via ServiceMonitor (Prometheus Operator) or target discovery.

7) Scaling & pooling:
   - Connection pooling configured via MONGO_MAX_POOL_SIZE env var.
   - Tune per-replica pool size and number of replicas for DB capacity.

