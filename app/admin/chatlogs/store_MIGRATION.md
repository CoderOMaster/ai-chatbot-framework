# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/chatlogs/store.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 12

## Breaking Changes
- Exposes functionality over HTTP REST endpoints (/chatlogs, /chatlogs/{thread_id}) rather than direct import of async functions — call sites must use HTTP clients or import the module and adapt.
- The module now initializes its own MongoDB client (using MONGODB_URI) with connection pooling; previous global app.database.client may be overridden or unused.
- Schema import path used: app.admin.chatlogs.schemas. If your project used a different relative .schemas import, adjust imports accordingly.
- Error handling now returns HTTP errors (404/503/500) for missing threads or DB issues; callers expecting None may need to handle HTTP responses.
- Service adds mandatory environment variables (MONGODB_URI, etc.). Default localhost values used for dev but must be provided in production.

## Migration Steps
1) Build and push the Docker image
   - docker build -t <registry>/chatlog-service:latest .
   - docker push <registry>/chatlog-service:latest

2) Kubernetes
   - Update the deployment YAML (kubernetes_manifest) with your image and MongoDB secret references.
   - kubectl apply -f k8s-deployment.yaml

3) Environment/Secrets
   - Provide MONGODB_URI as a Kubernetes Secret or AWS Secrets Manager when running in EKS/ECS.
   - Do not hardcode credentials in the image.

4) Readiness & Liveness
   - The service exposes /health and /readiness endpoints. Use those in your platform probes.

5) Logging
   - Logs are emitted as structured JSON to stdout. Configure your log aggregator (Fluentd/CloudWatch/Stackdriver) to parse JSON.

6) Prometheus
   - Metrics at /metrics for Prometheus scraping. Add ServiceMonitor or scrape config in Prometheus.

7) Graceful shutdown
   - The container listens for SIGTERM and will close the MongoDB connection during FastAPI shutdown events. Ensure platform's terminationGracePeriodSeconds is >= a few seconds to allow cleanup.

8) Connection pooling
   - Mongo client is created with configurable min/max pool sizes via environment variables MONGODB_MAX_POOL_SIZE and MONGODB_MIN_POOL_SIZE.

9) Compatibility
   - If your codebase relies on app.database.client, the service will attempt to set app.database.client to the new motor client for compatibility.

