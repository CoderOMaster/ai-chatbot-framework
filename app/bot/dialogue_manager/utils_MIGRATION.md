# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/dialogue_manager/utils.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 4

## Breaking Changes
- Application now exposes HTTP endpoints (/ , /health, /readiness, /split, /metrics, /db/health). Consume via HTTP instead of importing utils.py directly.
- SilentUndefined class is preserved but now lives inside the service module; importing path differs if you rely on original package structure.
- Logging is now JSON structured (python-json-logger) — consumers of plaintext logs must adapt.
- DB_URL is required to enable DB-related endpoints; if not provided DB features are disabled and readiness will report 'db: unconfigured'.
- The microservice uses FastAPI and uvicorn; existing sync import-and-run patterns must be adapted to service semantics.

## Migration Steps
1) Build and publish the container image
   - docker build -t your-registry/ai-chatbot-utils:latest .
   - docker push your-registry/ai-chatbot-utils:latest

2) Provision Kubernetes/EKS cluster (example using Terraform)
   - Populate variables (VPC, subnets, etc.) and run terraform init && terraform apply
   - Get kubeconfig (terraform output kubeconfig) and configure kubectl

3) Deploy application to Kubernetes
   - kubectl apply -f k8s/ai-chatbot-namespace.yaml
   - kubectl apply -f k8s/ai-chatbot-deployment.yaml
   - Ensure your DB secret is created: kubectl create secret generic ai-chatbot-db-secret --from-literal=DB_URL="postgresql+psycopg2://user:pass@host:5432/db"

4) Verify
   - kubectl get pods -n ai-chatbot
   - kubectl logs deploy/ai-chatbot-utils -n ai-chatbot
   - curl http://<cluster-ip-or-ingress>/health

5) Observability
   - Visit /metrics for Prometheus scraping
   - Logs are emitted as structured JSON for easier ingestion (CloudWatch/ELK/Datadog)

6) Rolling updates and scaling
   - Use kubectl set image or update Deployment image and apply
   - HPA can be added later based on CPU or custom metrics

7) Graceful shutdown
   - The service listens for SIGTERM and disposes DB connections in the shutdown handler. Kubernetes terminationGracePeriodSeconds is set on the Pod spec.

