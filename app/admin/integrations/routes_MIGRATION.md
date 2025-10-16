# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/integrations/routes.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 12

## Breaking Changes
- The service now expects configuration via environment variables (DB_DSN, DB_MAX_POOL, METRICS_ENABLED, LOG_LEVEL, etc.). Update deployment manifests to provide them.
- Structured JSON logging is enabled; logs format changed (machines downstream must parse JSON now).
- App initializes/tears down DB connection pool at startup/shutdown using store.init_pool / store.close_pool or connect/disconnect — ensure these functions exist or adapt store accordingly.
- Readiness endpoint may call store.is_ready or store.ping if present; implement these in store for accurate readiness checks.
- Uvicorn/ASGI entrypoint is provided. If previously run under a different server or style, update your container CMD accordingly.
- Metrics endpoint /metrics enabled; ensure Prometheus or scraping configuration expects this path and content type.
- Signal handling is improved for graceful shutdown; ensure terminationGracePeriodSeconds in k8s matches needs for draining long requests and closing DB connections.

## Migration Steps
1) Build and push image
   - Update the image name in the k8s manifest and CI pipeline to push to your container registry (ECR/GCR/ACR).
   - Build: docker build -t <registry>/integrations-service:latest .
   - Push: docker push <registry>/integrations-service:latest

2) Secrets
   - Create a Kubernetes Secret named integrations-db-secret containing your DATABASE_URL (DB_DSN).
     e.g. kubectl create secret generic integrations-db-secret --from-literal=DATABASE_URL='postgres://user:pass@host:5432/db'

3) Deploy to Kubernetes
   - kubectl apply -f k8s/namespace.yaml
   - kubectl apply -f k8s/deployment.yaml
   - Ensure service account RBAC and network / DNS config are correct.

4) Monitoring and logging
   - Ensure Prometheus scrapes the /metrics endpoint. The service exposes metrics at /metrics when METRICS_ENABLED is true.
   - Structured logs will be emitted in JSON to stdout/err; configure cluster logging to capture them (FluentD/FluentBit -> Elasticsearch/Cloud Logging).

5) DB connection pooling
   - The microservice calls store.init_pool(DB_DSN, max_pool). Ensure the store module implements one of these signatures:
       async def init_pool(dsn: str, max_size: int = 10)
       OR
       async def connect(dsn: str)
   - On shutdown the service calls store.close_pool() or store.disconnect() if available.

6) Readiness/Liveness
   - The Kubernetes manifest uses /readiness and /health. If the store exposes a ping/is_ready method, readiness will check DB connectivity.

7) Graceful shutdown
   - SIGTERM is handled; uvicorn also supports graceful shutdown. Keep replica counts and pod terminationGracePeriodSeconds aligned with connection draining.

8) Terraform
   - Use the provided Terraform snippets to create ECR/EKS or ECS resources. Replace placeholders and fill in IAM roles, VPC subnets, security groups, and other org-specific items.

