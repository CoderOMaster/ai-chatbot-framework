# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/entities/store.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- Exposed functionality as HTTP API endpoints (create/list/get/update/delete/bulk/synonyms). Callers must use REST instead of importing store.py functions directly.
- Database client initialization moved into the service and driven by MONGODB_URI/MONGODB_DB environment variables. Existing app.database is not used by default.
- Return shapes are Pydantic model dumps (dict) rather than raw motor documents; MongoDB _id is mapped to 'id' in Entity model when using the fallback. If your existing code depended on raw MongoDB documents, adapt callers.
- Endpoints use HTTP status codes (201 for create, 204 for update/delete). Consumers must handle these statuses accordingly.
- Logging changed to structured JSON logs via structlog. Upstream log parsing should be updated to expect JSON formatted logs.
- Prometheus metrics endpoint (/metrics) added. If you had a different metrics approach, integrate or disable as needed.

## Migration Steps
1. Build & test locally
   - Ensure Python dependencies installed (see requirements.txt)
   - Run locally: MONGODB_URI set to local MongoDB, then: python store.py or uvicorn store:app --reload

2. Build container image
   - docker build -t <your-registry>/entity-store:latest .
   - docker push <your-registry>/entity-store:latest

3. Deploy to Kubernetes
   - Update the k8s manifest image field to point to your image
   - kubectl apply -f k8s_manifest.yaml
   - Configure secrets for MONGODB_URI if using a managed MongoDB instance

4. Deploy to AWS (ECS Fargate)
   - Push image to ECR
   - Apply Terraform configuration (fill in variables) to create ECS service and task definition

5. Health checks & readiness
   - Kubernetes liveness probe -> /health
   - Kubernetes readiness probe -> /readiness

6. Logging & monitoring
   - Logs are emitted as JSON (structlog). Configure your log aggregation to parse JSON.
   - Prometheus metrics exposed at /metrics. Configure Prometheus scrape config.

7. Graceful shutdown
   - Service handles SIGTERM and will close MongoDB connections on shutdown.

8. Database considerations
   - No schema migrations are required by this service. If you need to modify stored entity shapes, handle via a data migration script.

