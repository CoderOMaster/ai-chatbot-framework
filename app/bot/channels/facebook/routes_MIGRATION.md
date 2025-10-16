# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/channels/facebook/routes.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 16

## Breaking Changes
- Entrypoint changed: service now expects app.bot.channels.facebook.routes:app as the ASGI application (previously routes.py was only a router).
- Logging format changed to structured JSON; any log parsing relying on plain text will need to be updated.
- A DB connection pool will attempt to initialize if DATABASE_URL is set and asyncpg is available. If your environment lacks asyncpg, pool will be skipped (non-fatal).
- Prometheus metrics are optional and gated by PROMETHEUS_ENABLED; previous deployments without this env var won't expose /metrics.
- New readiness and health endpoints: /health and the path configured with READINESS_PATH (default /ready).
- Signal handling improved for graceful shutdown; behavior slightly different in non-uvicorn run modes (script mode stops the loop on SIGTERM).
- FacebookReceiver import fallback: the module attempts absolute import first and falls back to relative import; ensure the package layout matches one of these.

## Migration Steps
1) Build your container image:
   - docker build -t <registry>/facebook-webhook:latest .
   - docker push <registry>/facebook-webhook:latest

2) Configure secrets and environment variables:
   - Create a secret for DATABASE_URL (if used) in Kubernetes: kubectl create secret generic db-secret --from-literal=DATABASE_URL='postgres://user:pass@host:5432/db'
   - Provide any other secrets the application uses (Facebook app tokens are read from the integration store, but if you use any env-driven config add them as secrets/environment variables).

3) Apply Kubernetes manifests:
   - kubectl apply -f k8s-deployment.yaml

4) For ECS/Fargate:
   - Use the Terraform snippet to create an ECS task and service, and ensure your container image is available in ECR.
   - Configure a load balancer and target group to route traffic to port 8000.

5) Monitoring & readiness:
   - Enable PROMETHEUS_ENABLED=true if you want the /metrics endpoint available.
   - Health check path: /health. Readiness check path configured via READINESS_PATH (default /ready).

6) Rolling upgrades:
   - Deploy new images via Kubernetes Deployment rolling update or ECS service deployment.

7) Logging:
   - Service logs are emitted as structured JSON to stdout. Configure your log collector (Fluentd, CloudWatch, Stackdriver) to parse JSON logs.

8) DB pooling:
   - If you provide DATABASE_URL and asyncpg is installed, a connection pool is created during startup. Ensure DB connection limits are sized appropriately to account for replicas and pool max_size.

