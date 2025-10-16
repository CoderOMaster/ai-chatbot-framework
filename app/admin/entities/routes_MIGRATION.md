# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/entities/routes.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- Added /health and /readiness endpoints (new endpoints)
- Added /metrics endpoint for Prometheus scraping
- Introduced structured JSON logging; log format changed from default
- Startup/shutdown lifecycle now attempts to call store.init() and store.close() if available
- SIGTERM handling and graceful shutdown behavior added; process may take GRACEFUL_SHUTDOWN_SECONDS before exiting
- Requests are now instrumented for Prometheus; extra dependencies added (prometheus-client)
- Routes now include error handling with 500/404 responses instead of raw exceptions
- Application is now an ASGI app meant to be run with uvicorn/gunicorn; direct invocation changed
- Environment variables control configuration (DB_URL, pool sizes, log level, port, readiness)
- Assumes store may expose optional health_check, init, close functions — you may need to update the store implementation to match

## Migration Steps
1) Build and push the container image:
   - docker build -t <your-registry>/entities-service:latest .
   - docker push <your-registry>/entities-service:latest

2) Configure secrets and environment variables:
   - Set DB_URL and other environment variables in your k8s Secret/ConfigMap or ECS task definition.
   - Ensure DB is reachable from the cluster (VPC, security groups, subnets).

3) Deploy to Kubernetes:
   - kubectl apply -f k8s_manifest.yaml
   - Monitor rollout: kubectl rollout status deployment/entities-deployment

4) For ECS/Fargate via Terraform:
   - Update Terraform variables with your VPC/subnet/SG and image registry values.
   - terraform init && terraform apply

5) Probes & Scaling:
   - Readiness probe hits /readiness. The service will not receive traffic until this returns 200.
   - Liveness probe hits /health. Containers will be restarted if unhealthy.

6) Logging & Observability:
   - Logs are JSON-formatted to stdout/stderr and will be collected by platform logging (CloudWatch/Fluentd).
   - Metrics are exposed at /metrics. Use Prometheus to scrape them or route to your monitoring system.

7) Graceful shutdown:
   - SIGTERM triggers _handle_sigterm which closes store connections and waits GRACEFUL_SHUTDOWN_SECONDS.
   - Tune GRACEFUL_SHUTDOWN_SECONDS based on request patterns.

8) Database connection pooling:
   - The service attempts to call store.init(DB_URL, min_size, max_size) during startup. Ensure your store implementation implements init/close and uses a pooled driver (asyncpg for Postgres, aiomysql for MySQL, motor for MongoDB, etc.).

9) Run locally:
   - export DB_URL="..."
   - uvicorn app.routes:app --host 0.0.0.0 --port 8000 --reload

