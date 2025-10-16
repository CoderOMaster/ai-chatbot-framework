# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/channels/rest/routes.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 40

## Breaking Changes
- routes.py has been refactored into a full FastAPI application and now validates input using Pydantic (WebbookRequest). Clients must send JSON compatible with {thread_id, text, context}.
- HTTPException now uses 'detail' (standard) instead of non-standard 'message' parameter.
- Added readiness checks that may return 503 if DB pool is not initialized; deployments depending on Readiness must ensure DB secrets and connectivity are configured.
- The application now expects environment variables (DB_DSN, DB_POOL_MIN, DB_POOL_MAX, METRICS_ENABLED, LOG_LEVEL). Add these to your deployment environment.
- Logging now produces structured JSON; log format changed which may affect downstream log processors that expect plain-text format.

## Migration Steps
1) Build and push container image
   - docker build -t your-registry/dialogue-service:latest .
   - docker push your-registry/dialogue-service:latest

2) Configure secrets and configmaps
   - Store DB_DSN and any API keys (OpenAI, etc.) in Kubernetes Secrets.
   - Reference them in deployment environment variables (see kubernetes_manifest).

3) Deploy to Kubernetes
   - kubectl apply -f k8s-deployment.yaml
   - Verify pods are running: kubectl get pods

4) Readiness & Liveness
   - The service exposes /rest/health and /rest/readiness. Set the Pod probes accordingly.

5) Logging & monitoring
   - Structured logs are emitted in JSON to stdout. Connect to your log aggregator (Fluentd/Fluent Bit / Cloud provider logging).
   - Metrics are exposed at /metrics (if METRICS_ENABLED=true and prometheus-client installed). Configure Prometheus scrape configs.

6) Graceful shutdown
   - The service installs SIGTERM handler and will attempt to close DB pools on shutdown. Configure Kubernetes Pod terminationGracePeriodSeconds > GRACEFUL_SHUTDOWN_TIMEOUT.

7) Scaling
   - Start with replicas: 3. Ensure your dialogue manager dependency and any ML services are horizontally scalable or use a shared model server.

8) DB connection pooling
   - The service uses asyncpg.create_pool when DB_DSN is provided. Tune DB_POOL_MIN/DB_POOL_MAX based on DB capacity.

9) CI/CD
   - Integrate image build and push into CI pipeline. Use Terraform or kubectl to apply manifests.

