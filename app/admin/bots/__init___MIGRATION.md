# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/bots/__init__.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 4

## Breaking Changes
- The refactored code assumes a package layout: service/__init__.py. Run with uvicorn service:app or python -m service.
- Environment variables are now required for configuration (DATABASE_URL, LOG_LEVEL, DB_POOL_*). If DATABASE_URL is missing, DB endpoints will return 503 where appropriate.
- Structured JSON logging replaced any previous ad-hoc print/log statements; log format changed and log consumers must parse JSON.
- Dependency on asyncpg and FastAPI/uvicorn added — ensure these are included in the environment.
- Metrics endpoint /metrics added (enabled with METRICS_ENABLED). If you previously relied on different metrics paths, update alerts/consumers.

## Migration Steps
1) File layout
   - Place the provided Python file at `service/__init__.py` (create folder `service`).
   - Keep requirements.txt at project root.

2) Build and push container image
   - docker build -t <registry>/service:latest .
   - docker push <registry>/service:latest

3) Kubernetes deployment
   - Update the Kubernetes manifest: replace `REPLACE_WITH_IMAGE` with the pushed image, and set DB secret value.
   - kubectl apply -f k8s-manifest.yaml

4) ECS Fargate (if using ECS)
   - Use the Terraform ECS snippet (fill out region, subnets, roles) to create ECS cluster and task definition.
   - Ensure secrets like DATABASE_URL are injected via AWS Secrets Manager or environment variables in Task Definition.

5) Health and readiness
   - /health returns quick liveness; /readiness validates DB connectivity when DATABASE_URL is set.
   - Configure Kubernetes liveness/readiness probes as provided.

6) Logging and observability
   - Logs are structured JSON to stdout/stderr ready for ingestion by Fluentd/CloudWatch/Stackdriver.
   - Prometheus metrics exposed at /metrics (enable with METRICS_ENABLED=true).

7) Graceful shutdown
   - The service listens for SIGTERM/SIGINT and will attempt graceful shutdown, closing DB pools on shutdown.

8) Local testing
   - pip install -r requirements.txt
   - python -m service
   - or: uvicorn service:app --host 0.0.0.0 --port 8000

9) Secrets
   - Do not commit DATABASE_URL or other secrets into git. Use Kubernetes Secrets, AWS Secrets Manager, or your cloud secret store.

