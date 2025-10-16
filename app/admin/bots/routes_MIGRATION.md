# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/bots/routes.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 12

## Breaking Changes
- Consolidated application entrypoint: The microservice now exposes a FastAPI app instance (app) with lifecycle management; if your deployment previously imported router directly, the entrypoint module path changed.
- Startup/shutdown now attempt to initialize and close database/store resources by calling common function names (init, initialize, connect, init_pool, close, shutdown, teardown, close_pool). If your store implementation does not expose any of these names the service will continue to run but lifecycle automation won't be invoked.
- Database pooling is optional and only created when DATABASE_URL is set and asyncpg is available. If you relied on implicit connection creation elsewhere, ensure DATABASE_URL and asyncpg are configured or maintain the previous store behavior.
- Logging format changed to structured JSON which may require updating log parsers/collectors.
- Prometheus metrics are optional and available only if prometheus_client is installed; include it in your image or adjust requirements.txt.
- SIGTERM handling added; in some hosting environments this may interplay with the platform's own signal handling (e.g., gunicorn or container orchestrator). Ensure graceful shutdown semantics are compatible with your environment.

## Migration Steps
- Build the container image using the provided Dockerfile and push to your container registry.
- Ensure environment variables are set (DATABASE_URL, LOG_LEVEL, etc.) via Kubernetes ConfigMap/Secret or ECS Task Definition.
- If your store implementation already manages connections (e.g. motor for MongoDB, boto3 for S3, custom SDK), the service will try to call common init/close functions (init/initialize/connect/init_pool and close/shutdown/teardown/close_pool) but will not require them. Adjust store to expose one of these if you want automatic pool propagation.
- Apply the Kubernetes manifest (kubectl apply -f k8s-manifest.yaml) after replacing <your-registry> and secrets.
- For ECS/Fargate, adapt and apply the Terraform ECS snippet after configuring provider, networking, and IAM roles.
- Monitoring: if you use Prometheus, scrape /metrics. Logs are JSON-structured to stdout for ingestion by log collectors.
- Health & readiness endpoints are available at /health and /readiness. Configure probes accordingly.
- To enable DB connection pooling, set DATABASE_URL. asyncpg must be present in the runtime if using a Postgres pool.

