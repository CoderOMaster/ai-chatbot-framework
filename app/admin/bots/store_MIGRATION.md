# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/bots/store.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 8

## Breaking Changes
- This file is now a standalone FastAPI microservice exposing HTTP endpoints. Any previous direct imports and synchronous invocation of functions inside store.py from other modules must be adjusted to call the REST endpoints.
- Database initialization is centralized in this module and monkeypatched onto app.database. If your original app.database has custom initialization/connection pooling logic, modify the startup_event to call that instead of monkeypatching.
- The original ensure_default_bot function was executed on-demand; the refactor ensures default bot existence at service startup. This will attempt to create the default bot during startup.
- Export/import endpoints retain the original behavior of ignoring the 'name' parameter for exported/imported data. If you relied on name-scoped exports previously, you will need to update the endpoints to filter by bot name.
- Logging format changed to structured JSON; downstream log consumers must be prepared to parse JSON logs rather than plain text.
- Prometheus metrics are optional and disabled by default; enabling requires prometheus_client dependency and setting ENABLE_METRICS=true.

## Migration Steps
1) Ensure app.database compatibility: This refactor programmatically creates an AsyncIOMotorClient and monkeypatches attributes (client, database) on the imported app.database module so other internal modules (app.admin.*) reuse the same connection. If your existing app.database provides a different initialization API, adapt to use that initialization in the startup handler.

2) Environment variables: Configure DB_URL, DB_NAME, DB_MAX_POOL_SIZE, DB_MIN_POOL_SIZE, ENABLE_METRICS, LOG_LEVEL, PORT. Example Docker/K8s env shown in manifest.

3) Health/readiness: /health returns OK for liveness; /readiness pings MongoDB. Configure platform liveness/readiness probes accordingly.

4) Logging: Structured JSON logs via python-json-logger. Ensure your log aggregator parses JSON.

5) Graceful shutdown: SIGTERM and SIGINT attempt to set an internal event; Uvicorn/Gunicorn will trigger FastAPI shutdown callbacks which close the motor client.

6) Connection pooling: DB_MAX_POOL_SIZE and DB_MIN_POOL_SIZE control Motor's pool size. Tune for your workload.

7) Metrics (optional): ENABLE_METRICS toggles Prometheus metrics (requires prometheus_client). Exposes /metrics when enabled.

8) Build and deploy: Build Docker image, push to registry, update k8s manifest image reference, then kubectl apply -f <manifest>. For ECS/EKS use Terraform snippets as a starting point.

9) Tests: Run integration tests against a real or mocked MongoDB. Ensure app.admin.* stores use the same database reference; if not, update app.database initialization accordingly.

