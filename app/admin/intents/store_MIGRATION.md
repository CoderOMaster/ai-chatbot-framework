# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/intents/store.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- Introduced HTTP REST API surface; callers of the previous store.py module must now use the HTTP endpoints instead of direct function imports.
- The service now expects environment variables (MONGO_URI, DB_NAME, etc.) — these must be provided in deployment manifests or runtime environment.
- Assumes Intent.model_validate exists (Pydantic v2 style). If your project Intent uses a different validation API, adjust the compatibility shim.
- Error handling changed: functions raise HTTPException with appropriate status codes instead of returning None or raising raw exceptions.
- Database client lifecycle is now managed by the FastAPI app lifespan; import-time side-effects from the original module are removed.
- Endpoints return JSON and use pydantic models for validation. The HTTP API shape (field names, presence of id vs _id) may differ from previous direct-returned objects.
- Added Prometheus metrics and JSON structured logging; log format changed from plain text to JSON which may impact existing log parsers.

## Migration Steps
1) Build and publish the container image
   - docker build -t your-registry/intent-service:latest .
   - docker push your-registry/intent-service:latest

2) Secrets and config
   - Store MONGO_URI in a Kubernetes Secret (intent-service-secrets) with key 'mongo_uri'.
   - Configure other environment values (DB_NAME, LOG_LEVEL) via ConfigMap or directly in the Deployment.

3) Deploy to Kubernetes
   - kubectl apply -f k8s/intent-service-deployment.yaml
   - Ensure the MongoDB service is reachable from the cluster (either managed MongoDB Atlas with VPC peering or an in-cluster MongoDB).

4) Readiness and liveness
   - The /readiness endpoint pings the database; ensure network egress and credentials are correct.
   - Tune readinessProbe initialDelaySeconds to allow DB warm-up.

5) Observability
   - Prometheus: scrape /metrics endpoint. Configure Prometheus scrape target for the service.
   - Logging: logs are JSON-formatted and should be shipped to your log aggregator (ELK/Datadog/CloudWatch).

6) Graceful shutdown
   - The service uses FastAPI lifespan to close the MongoDB client. Set Kubernetes terminationGracePeriodSeconds >= 30.

7) Scaling
   - The MongoDB connection pool size and replica counts should be tuned together. If scaling Pods aggressively, set MONGO_MAX_POOL_SIZE appropriately and ensure MongoDB can handle total connections.

8) CI/CD
   - Integrate image build and k8s manifest deployment in your CI/CD pipeline. Use image tags and rollout strategies for safe upgrades.

