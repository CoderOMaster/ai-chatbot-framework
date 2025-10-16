# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/integrations/schemas.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 2

## Breaking Changes
- settings default changed from mutable {} to None to avoid shared mutable default. The code now sets settings to {} if omitted when creating/updating integrations.
- Service now exposes Prometheus metrics (/metrics) and readiness/liveness endpoints; if your orchestration expects different endpoints you must adapt probes.
- DB initialization is optional: if DATABASE_URL is set it uses SQLAlchemy async engine (requires an async driver like asyncpg and an async URL scheme e.g. postgresql+asyncpg://).
- Structured JSON logging is enabled, which changes log format for downstream log consumers.
- The application now runs as an ASGI service (FastAPI + Uvicorn). If any consumer expected to import the original schemas.py directly as a module, schemas are still included but default for 'settings' field changed.

## Migration Steps
1) Build and test locally
   - Install dependencies from requirements.txt in a virtualenv.
   - Run app locally: uvicorn app:app --reload --port 8000

2) Configure environment variables
   - LOG_LEVEL, DATABASE_URL (optional), DB_POOL_SIZE, DB_MAX_OVERFLOW
   - For Kubernetes or ECS, store DATABASE_URL in a secret and reference it in the pod/task definition.

3) Build and push Docker image
   - docker build -t <registry>/integration-service:latest .
   - docker push <registry>/integration-service:latest

4) Deploy to Kubernetes
   - Update image path in k8s manifest and apply: kubectl apply -f k8s_manifest.yaml
   - Ensure DB secret is created: kubectl create secret generic db-secret --from-literal=DATABASE_URL='postgresql+asyncpg://user:pass@host:5432/db'

5) (Optional) Deploy to ECS Fargate using Terraform
   - Provide container image, VPC/Subnets/IAM roles in Terraform variables and run terraform apply

6) Observability
   - The service exposes /metrics for Prometheus scraping
   - Use pods' /health and /readiness for liveness/readiness probes

7) Graceful shutdown
   - The app handles SIGTERM by marking readiness false, disposing DB connections, and exiting.

8) Database
   - This refactor keeps an in-memory store for Integration objects for compatibility/testing. Replace with persistent DB models if you need durable storage. Use the provided SQLAlchemy async engine (created when DATABASE_URL is provided) for connection pooling.

