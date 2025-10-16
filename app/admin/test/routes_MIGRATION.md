# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/test/routes.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 24

## Breaking Changes
- Routes file was refactored and combined into a standalone FastAPI service (entrypoint: service:app). If you previously relied on importing the old routes module path, update imports accordingly.
- Environment variables are now required/configurable: DATABASE_URL, REDIS_URL, LOG_LEVEL, DATABASE_POOL_SIZE. Absence of DATABASE_URL means DB features are disabled and endpoints that depend on DB will return 503 if they attempt DB access.
- Structured JSON logging is enabled and replaces any previous text/print logs; log consumers should expect JSON-formatted logs.
- Health and readiness endpoints added (/health and /readiness). Readiness will return 503 until DB/Redis readiness checks pass when configured.
- Graceful shutdown behavior added; the service attempts to close DB/Redis pools on SIGTERM. Ensure terminationGracePeriodSeconds in Kubernetes is set appropriately.
- Prometheus metrics are optionally enabled if prometheus_client is installed; endpoint exposed at /metrics. If not installed, /metrics will not be available.
- The Dockerfile now uses multi-stage build and the default command runs uvicorn. If you were running via a different command/login, update your runtime commands accordingly.

## Migration Steps
1) Build the container image
   - docker build -t your-registry/dialogue-manager:latest .
   - Push to your registry (ECR/GCR/Private): docker push your-registry/dialogue-manager:latest

2) Provision infrastructure
   - For Kubernetes: apply the kubernetes_manifest (kubectl apply -f k8s.yaml)
   - For ECS: use the provided Terraform to create cluster, task definition, and service

3) Configure secrets and environment variables
   - Create Kubernetes Secrets for DATABASE_URL and REDIS_URL
   - Ensure LOG_LEVEL and other optional env vars set via Deployment

4) DB Migration & Connection Pooling
   - Ensure DATABASE_URL points to an async-capable DB driver (asyncpg for Postgres)
   - Migration tools (alembic) should be used out-of-band prior to starting the service

5) Observability
   - Prometheus can scrape /metrics if prometheus_client is installed
   - Logs are structured JSON to stdout for easy ingestion by logging systems

6) Graceful Shutdown
   - The service listens for SIGTERM and performs resource cleanup (DB dispose, Redis close)
   - When using Kubernetes, set terminationGracePeriodSeconds sufficiently (e.g., 30 - 60s)

7) Scale and Resource Tuning
   - Tune DATABASE_POOL_SIZE to match expected concurrency and DB capacity
   - Tune CPU/memory requests and limits in the Deployment according to load

