# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/integrations/store.py
- Deployment: Microservice
- Complexity: Low
- Estimated Hours: 4

## Breaking Changes
- This code refactors DB initialization: the service now creates its own Motor Mongo client at startup instead of relying on an external app.database module. Update imports or remove the old shared database instance.
- APIs exposed via FastAPI endpoints (/integrations, /integrations/{id}, /integrations/{id} PATCH, /integrations/ensure-defaults). If previously the store was only a library, consumers must now use HTTP.
- Configuration is environment-driven via MONGODB_URI, MONGODB_DB, MONGO_MAX_POOL_SIZE, LOG_LEVEL, METRICS_ENABLED; ensure environment variables are set in deployment.
- Logging format changed to structured JSON. Any log parsing expecting plain-text must be updated.
- Startup behavior now ensures default integrations on startup; remove duplicate initialization if it exists elsewhere.
- The microservice uses Pydantic v2 model_dump() semantics for IntegrationUpdate; ensure your models are compatible with pydantic v2.

## Migration Steps
1) Build and push image
   - docker build -t your-registry/integrations-service:latest .
   - docker push your-registry/integrations-service:latest

2) Configure environment
   - provide MONGODB_URI pointing to your MongoDB (use a Secret in k8s for credentials)
   - set MONGODB_DB and MONGO_MAX_POOL_SIZE as needed

3) Deploy to Kubernetes
   - kubectl apply -f k8s-deployment.yaml
   - Ensure Service and Ingress (if external access) are configured

4) ECS/Fargate
   - push image to ECR
   - apply Terraform ECS resources or create a task definition/service referencing the image

5) Observability
   - Scrape /metrics from Prometheus if METRICS_ENABLED=true
   - Logs are emitted in JSON format; configure log collection (CloudWatch, ELK, etc.)

6) Zero-downtime & scaling
   - Use replica count >= 2 for redundancy
   - Set HPA rules based on CPU, memory, or custom metrics

7) Secrets
   - Move sensitive values (Mongo URI) to Kubernetes Secrets or AWS Secrets Manager (in ECS/EKS)

8) DB migrations
   - Ensure initial defaults are inserted at startup (service does this automatically). For schema changes, add migration jobs or use a migration tool.

