# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/channels/__init__.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 4

## Breaking Changes
- Code reorganized into a FastAPI microservice; original (empty) code replaced with standardized endpoints and lifecycle.
- Application now requires DATABASE_URL env var for DB-backed routes; if not provided DB-related endpoints will be disabled but readiness will report ready.
- Logging now emits structured JSON logs which may break text-based parsers expecting plaintext logs.
- Default server startup uses Gunicorn+Uvicorn worker in Dockerfile; if you previously relied on a different entrypoint change startup commands accordingly.
- Metrics endpoint /metrics was added and returns Prometheus format; ensure Prometheus scrape config updated.

## Migration Steps
1) Build and test locally
   - Ensure you have Python 3.11+ and installed requirements: pip install -r requirements.txt
   - Run locally: python -m app  (or) uvicorn app:app --host 0.0.0.0 --port 8000

2) Container build and push
   - docker build -t <registry>/fastapi-microservice:latest .
   - docker push <registry>/fastapi-microservice:latest

3) Kubernetes deployment
   - Update image path in the kubernetes manifest to the pushed image
   - kubectl apply -f k8s-manifest.yaml
   - kubectl rollout status deployment/fastapi-microservice

4) ECS/Fargate deployment with Terraform (optional)
   - Fill in Terraform variables (VPC, subnets, image, AWS region)
   - terraform init && terraform apply

5) Environment and secrets
   - Use Kubernetes Secrets or a secret manager for DATABASE_URL and other secrets
   - On ECS/Fargate, use AWS Secrets Manager or SSM Parameter Store for secure injection

6) Observability
   - Scrape /metrics endpoint with Prometheus
   - Structured logs are JSON so they can be consumed by centralized logging (e.g., ELK, CloudWatch)

7) Graceful shutdown
   - The app listens to SIGTERM/SIGINT to close DB connections. Ensure your process manager (kubelet, ECS agent) allows enough terminationGracePeriodSeconds (e.g. 30s).

8) Database pooling
   - Configure DB_POOL_SIZE and DB_MAX_OVERFLOW via environment variables according to your DB sizing and concurrency

9) Scaling
   - Horizontal scaling is recommended. For Kubernetes use HorizontalPodAutoscaler based on CPU or custom metrics. For ECS use Service Auto Scaling.

