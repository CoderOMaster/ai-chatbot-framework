# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/__init__.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- The service now requires environment variables (DB_URL, DB_POOL_SIZE, DB_MAX_OVERFLOW, LOG_LEVEL, REQUEST_METRICS). Provide defaults in env or configure them in deployment.
- Logging format changed to structured JSON via python-json-logger. Consumers of plain-text logs must update parsers.
- DB connection pooling is handled via SQLAlchemy engine. Ensure DB supports the increased number of connections across replicas, tune pool sizes accordingly.
- The application entrypoint is package app (app/__init__.py). Docker and deployment manifests expect the package path when running uvicorn.
- Prometheus metrics are enabled via REQUEST_METRICS env var. If disabled, /metrics returns 404 text; monitoring should expect metrics only when enabled.

## Migration Steps
1) Build and test locally
   - Ensure you have Python 3.11 (or pinned version) and the dependencies installed.
   - To run locally: set environment variables (DB_URL, DB_POOL_SIZE, etc.) and run:
       uvicorn app:app --host 0.0.0.0 --port 8000 --reload

2) Containerize
   - Build image:
       docker build -t <your-registry>/example-microservice:latest .
   - Push to your container registry (ECR/GCR/ACR/DockerHub).

3) Deploy to Kubernetes (EKS/GKE/AKS)
   - Update the k8s manifest image field with your registry image.
   - kubectl apply -f k8s-deployment.yaml
   - Verify pods are Running and readiness/liveness probes succeed.

4) Deploy to ECS/Fargate (if chosen)
   - Push image to ECR and update task definition image.
   - Create/Update service to use new task definition.

5) Observability
   - Scrape /metrics using Prometheus if REQUEST_METRICS=true.
   - Collect logs from stdout (JSON structured logs) via your logging agent (Fluentd/CloudWatch/Stackdriver).

6) Database
   - Ensure DB_URL is set to a managed DB or connection string with network connectivity (VPC, security groups).
   - Tune DB_POOL_SIZE and DB_MAX_OVERFLOW based on DB capacity and container replica counts.
   - Migrations: perform any DB migrations before switching traffic to the new service run.

7) Graceful shutdown
   - The app registers a SIGTERM handler and ties shutdown to engine.dispose(); container orchestrators should send SIGTERM and wait for terminationGracePeriod to allow in-flight requests to finish.

8) CI/CD
   - Integrate build/push and kubectl apply in your pipeline. Use image tags for safe rollouts.

