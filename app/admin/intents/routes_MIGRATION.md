# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/intents/routes.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- Added environment variables (DB_URL, POOL_MIN, POOL_MAX, LOG_LEVEL, METRICS_ENABLED). You must set these in your deployment.
- The store module must expose an initializer (init_pool / initialize / connect) and a close/disconnect/shutdown function for proper lifecycle handling. If not present, the service will still start but readiness checks may be optimistic.
- Logging format changed to structured JSON; consumers of logs must parse JSON rather than plain text.
- Prometheus metrics now optionally expose /metrics (requires prometheus-client).
- Signal handling and graceful shutdown behavior added — ensure platform forwards SIGTERM properly and terminationGracePeriodSeconds is sufficient.

## Migration Steps
Deployment steps (high-level):

1. Update store implementation
   - Ensure app.admin.intents.store exposes one of the following init/close function names:
     - init_pool(db_url, min_size, max_size) [async preferred]
     - initialize(db_url) / connect(db_url)
     - And a close/disconnect/shutdown function for cleanup
   - Optionally provide a ping() or is_healthy() function used by /ready probe.

2. Build & publish Docker image
   - docker build -t <registry>/intents-service:latest .
   - docker push <registry>/intents-service:latest

3. Create/Update Kubernetes resources
   - kubectl apply -f k8s_manifest.yaml
   - Configure DB credentials as Kubernetes Secrets and reference them in Deployment envFrom/secretKeyRef.

4. Configure observability
   - Mount Prometheus scrape config or enable metrics at /metrics (ensure prometheus-client is installed).
   - Centralized logging expects JSON logs; configure your logging backend (Fluentd/Fluent-bit/CloudWatch) to parse JSON.

5. Gradual rollout
   - Start 1 replica, monitor readiness and logs, then scale to desired replicas.

6. Health checks and graceful shutdown
   - The container responds to SIGTERM and attempts to close DB pools on shutdown. Kubernetes default preStop and terminationGracePeriodSeconds should be tuned to allow in-flight requests to finish (e.g., terminationGracePeriodSeconds: 30-120).

7. Secrets & config
   - Use Kubernetes Secrets for DB credentials; do not embed secrets in images.
   - Tune POOL_MIN and POOL_MAX via env vars for your DB capacity.

