# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/channels/rest/__init__.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 16

## Breaking Changes
- This refactor introduces a FastAPI-based HTTP server (previous file was empty). If you had prior imports or behavior, they are replaced.
- New required environment variables: DATABASE_URL (if DB access required). The app will not fail startup without DB but readiness may fail if your app depends on DB.
- Structured JSON logging (structlog) is now used; log format has changed from plain text to JSON.
- Endpoint contract: /readiness returns 503 when not ready. Orchestrators should use readiness for traffic control.
- Application lifecycle now includes a DB connection pool which will be initialized on startup and closed on shutdown. Any code expecting synchronous DB connections will need adaptation.
- Prometheus metrics are enabled by default and exposed at /metrics (can be disabled via METRICS_ENABLED=false).
- Signal handling behavior: SIGTERM sets readiness to false quickly; ensure your orchestrator's terminationGracePeriodSeconds allows for graceful shutdown.

## Migration Steps
1) Build and test locally
   - Install deps from requirements.txt.
   - Run locally with: uvicorn __init__:app --host 0.0.0.0 --port 8000
   - Endpoints:
     - GET /health -> liveness
     - GET /readiness -> readiness
     - GET /metrics -> Prometheus metrics (if enabled)
     - GET /db/ping -> tests DB connectivity (requires DATABASE_URL)
     - POST /echo -> {"message": "..."}

2) Containerize
   - docker build -t YOUR_REGISTRY/microservice:latest .
   - docker push YOUR_REGISTRY/microservice:latest

3) Kubernetes deployment
   - Replace image placeholder in kubernetes_manifest with the built image URI.
   - Create k8s secret for DATABASE_URL (kubectl create secret generic my-db-secret --from-literal=DATABASE_URL="postgres://user:pass@host:5432/db").
   - kubectl apply -f k8s-manifest.yaml
   - Verify pods: kubectl get pods
   - Check readiness/liveness: kubectl describe pod <pod>

4) Observability
   - Point Prometheus to scrape /metrics endpoint.
   - Logs are structured JSON via structlog; configure your log aggregator (e.g., Fluentd/CloudWatch) to parse JSON.

5) Graceful shutdown and readiness
   - On SIGTERM the app will set readiness to false quickly, allowing Kubernetes/ECS to stop sending traffic.
   - The shutdown event will close DB connection pool cleanly.

6) Secrets and config
   - Do not store DATABASE_URL in plain env vars in production. Use Kubernetes Secrets, AWS Secrets Manager, or parameter store.

7) Scaling
   - HPA can be added for CPU/memory-based scaling. With Kubernetes, ensure liveness/readiness probes are tuned according to your app startup/shutdown times.

