# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/nlu/__init__.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 24

## Breaking Changes
- The original repository contained no runnable code; this introduces a new FastAPI-based microservice with endpoints /, /health, /readiness, /metrics, and /db/status.
- Environment variable configuration via Pydantic Settings is now required for runtime configuration (APP_ENV, DB_URL, DB_POOL_SIZE, DB_MAX_OVERFLOW). Defaults are provided.
- Logging format changed to structured JSON (python-json-logger). Consumers expecting plain text logs will need to adapt.
- Database connectivity now uses SQLAlchemy engine with pooling. Behavior differs if previous code used ad-hoc DB connections.
- Prometheus metrics endpoint added at /metrics — ensure this port/path is allowed and scraped by monitoring systems.
- Container entrypoint changed to run uvicorn; orchestration must be configured to use port 8000 and respect graceful termination.

## Migration Steps
1. Build and test locally:
   - Create a virtualenv: python -m venv .venv && source .venv/bin/activate
   - Install deps: pip install -r requirements.txt
   - Run locally: python __init__.py (or uvicorn __init__:app --reload)

2. Dockerize and push:
   - docker build -t <YOUR_REGISTRY>/nlp-microservice:latest .
   - docker push <YOUR_REGISTRY>/nlp-microservice:latest

3. Kubernetes:
   - Replace image in k8s manifest with your registry image.
   - kubectl apply -f k8s-manifest.yaml

4. Terraform (ECS/Fargate):
   - Fill variables and run terraform init && terraform apply

5. Health checks:
   - K8s livenessProbe -> /health
   - K8s readinessProbe -> /readiness

6. Logging:
   - Structured JSON logs go to stdout/stderr and can be collected by your logging stack (Fluentd, CloudWatch, etc.).

7. Database:
   - Provide DB_URL via Kubernetes Secret or environment variable; use a managed DB for production.
   - Connection pooling configured via DB_POOL_SIZE and DB_MAX_OVERFLOW environment variables.

8. Metrics:
   - Prometheus scrapes /metrics. Ensure network policies and ServiceMonitor (if using Prometheus Operator) are configured.

9. Graceful shutdown:
   - On SIGTERM the app marks readiness = false and disposes DB connections on shutdown. Ensure Kubernetes terminationGracePeriodSeconds is sufficient for in-flight requests.

