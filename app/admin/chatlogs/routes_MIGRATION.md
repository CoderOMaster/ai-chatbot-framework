# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/chatlogs/routes.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- Logging format changed to structured JSON (python-json-logger). Downstream systems must parse JSON logs or adjust ingestion.
- Health and readiness endpoints added (/health, /readiness). Readiness checks DB connectivity when DB_DSN is configured; previously there was no readiness endpoint.
- Error responses now use JSONResponse with proper HTTP status codes for not found and server errors (e.g., 404 for conversation not found).
- The service now initializes DB connection pooling on startup. store module must provide one of the expected functions (init_pool, init, connect_pool, setup) or be compatible with the fallback behavior.
- Prometheus metrics optionally enabled if prometheus_client is installed; metrics endpoint path controlled by METRICS_PATH env var (defaults to /metrics).

## Migration Steps
1) Build and publish container image
   - docker build -t YOUR_REGISTRY/chatlogs:latest .
   - docker push YOUR_REGISTRY/chatlogs:latest

2) Create or apply Kubernetes resources
   - kubectl apply -f k8s_manifest.yaml
   - Ensure secrets (chatlogs-db-secret) exist with DB_DSN

3) For AWS ECS/Fargate using Terraform
   - Configure variables (db_dsn, aws_region, private_subnets, sg_id)
   - terraform init && terraform apply
   - Push image to ECR repository referenced in terraform

4) Runtime/Operation
   - Use readiness (/readiness) and liveness (/health) probes in orchestrator
   - Monitor /metrics endpoint with Prometheus if enabled
   - Configure log ingestion to accept JSON logs (structured logs) into your logging stack (Fluentd/Fluentbit/CloudWatch)

5) Secrets & Config
   - Store DB_DSN as a secret (Kubernetes Secret, AWS Secrets Manager or Parameter Store)
   - Do NOT bake credentials into the image

6) Rolling upgrades
   - Use standard k8s rolling updates or ECS deployment strategy. The app listens for SIGTERM to close DB pools; ensure grace period >= GRACEFUL_TIMEOUT

7) Local dev
   - Use docker-compose or a local Postgres and set DB_DSN to point at it. If DB not provided, readiness returns ready but DB-related endpoints may not work.

