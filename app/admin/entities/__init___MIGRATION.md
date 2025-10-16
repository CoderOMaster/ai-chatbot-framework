# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/entities/__init__.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- No original application logic was present — introduced a new FastAPI microservice structure.
- Service entrypoint changed: package now expects to be served as a Python package (uvicorn app:app).
- Environment variables are required/optional: DATABASE_URL now controls readiness and DB endpoints; services depending on implicit DB availability must set it.
- Logging format changed to structured JSON; log consumers must parse JSON logs instead of plain text.
- Shutdown behavior: application will honor SIGTERM and attempt graceful shutdown; ensure orchestration terminationGracePeriodSeconds is configured.
- Prometheus metrics endpoint exposed at /metrics (enabled by default). If not desired, set PROMETHEUS_ENABLED=false.
- Database connectivity now uses asyncpg connection pooling. If your previous code used a different DB library, adapt queries to asyncpg or add a compatibility layer.

## Migration Steps
1) Build & publish container image
   - Ensure repository root contains the package folder 'app' with this __init__.py, and requirements.txt.
   - Build image: docker build -t <REGISTRY>/example-service:latest .
   - Push to your registry: docker push <REGISTRY>/example-service:latest

2) Kubernetes (EKS) deployment
   - Create secret for DATABASE_URL (example using kubectl):
       kubectl create secret generic example-db-secret --from-literal=database_url='postgres://user:pass@host:5432/dbname' -n <namespace>
   - Update k8s manifest image to your image registry and apply:
       kubectl apply -f k8s-deployment.yaml
   - Monitor rollout: kubectl rollout status deployment/example-service

3) ECS/Fargate deployment
   - Push the image to ECR
   - Update terraform variables and run terraform init && terraform apply
   - Ensure secrets are provided via Secrets Manager/SSM and container environment references are updated

4) Observability & Health
   - Liveness: /health
   - Readiness: /readiness (includes DB check if DATABASE_URL present)
   - Metrics: /metrics (Prometheus format) if PROMETHEUS_ENABLED=true
   - Logs are structured JSON via python-json-logger; send to your log collector (Fluentd, CloudWatch, ELK)

5) Graceful shutdown
   - Kubernetes: set terminationGracePeriodSeconds >= GRACEFUL_SHUTDOWN_SECONDS (default 30s) in manifest.
   - Uvicorn receives SIGTERM; the app listens for SIGTERM and attempts to close DB pool and stop the loop gracefully.

6) Secrets & Configuration
   - Do not embed DATABASE_URL in images. Use Kubernetes Secrets, AWS Secrets Manager, or environment injection by your orchestrator.

7) Scaling & Resources
   - Replica settings in manifest: replicas=3, resource requests as indicated. Tune according to load.

8) CI/CD
   - Integrate image build & push into your CI (GitHub Actions, GitLab CI, etc).
   - Use image tags (e.g., commit SHA) for immutable deployments.

