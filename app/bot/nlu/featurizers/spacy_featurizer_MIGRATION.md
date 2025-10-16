# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/nlu/featurizers/spacy_featurizer.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 16

## Breaking Changes
- The component is now exposed as an HTTP microservice; callers must call /featurize or /train instead of importing and invoking the class directly.
- Responses contain a serialized 'spacy_doc' (tokens, ents, sents). The original in-memory spaCy Doc object is not returned over HTTP (not JSON serializable).
- Logging format changed to structured JSON. Existing log parsers may need adjustments.
- New dependencies added (FastAPI, uvicorn, SQLAlchemy, psycopg2-binary, Prometheus client).
- Service expects environment variables like SPACY_MODEL and DATABASE_URL; update deployment configurations accordingly.
- Startup now attempts to load the spaCy model on initialization and will crash if model cannot be loaded (Kubernetes restart will be triggered).

## Migration Steps
1) Build the Docker image
   - Ensure required system packages (gcc, libpq-dev, etc.) are installed in the build image.
   - Pre-install the spaCy model into the image or mount the model assets at runtime. Example inside Dockerfile: python -m spacy download en_core_web_sm or pip install en_core_web_sm.

2) Push to container registry
   - Tag and push the image to ECR/GCR/your registry.

3) Configure Kubernetes
   - Apply the provided Kubernetes manifest (kubectl apply -f k8s.yaml).
   - Ensure the namespace in the Terraform / k8s manifests matches the EKS Fargate profile selector if using Fargate.

4) Environment & Secrets
   - Provide DATABASE_URL via Kubernetes Secret and mount as environment variable.
   - Tune DB_POOL_SIZE and DB_MAX_OVERFLOW according to your DB and concurrency requirements.

5) Observability
   - Metrics exposed at /metrics. Configure Prometheus to scrape this endpoint.
   - Logs are JSON structured to stdout/err for collection by Fluentd/Fluent Bit/CloudWatch.

6) Graceful shutdown
   - The service listens for SIGTERM and uses FastAPI lifecycle events to dispose DB connections.
   - Kubernetes preStop hooks and pod terminationGracePeriodSeconds should be configured to allow graceful shutdown.

7) Model management
   - For large models consider mounting model data from a shared persistent volume or downloading model in initContainers to avoid large images.

8) Security
   - Run the container under a non-root user in production.
   - Limit RBAC in the cluster and secure access to database credentials.

