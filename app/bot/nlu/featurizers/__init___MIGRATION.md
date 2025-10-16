# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/nlu/featurizers/__init__.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 16

## Breaking Changes
- Replaced simple module __init__ exposing SpacyFeaturizer with a full FastAPI ASGI app object named `app`. Consumers importing the package should now use `app` for the microservice (e.g., uvicorn app.__init__:app).
- Initialization now performs spaCy model loading and instantiates SpacyFeaturizer at startup. If the featurizer previously expected different instantiation semantics, adjust SpacyFeaturizer to accept an `nlp` argument, or modify the startup logic.
- Added dependency on FastAPI, uvicorn, SQLAlchemy, prometheus-client and python-json-logger — update your environment and image build.
- If you relied on importing SpacyFeaturizer directly via `from app.bot.nlu.featurizers import SpacyFeaturizer`, this remains possible but the package now also provides the ASGI `app` variable from __init__. Adjust import paths if necessary.
- Container image must include spaCy model or allow download at startup (controlled by MODEL_DOWNLOAD). This can increase startup time if downloading models on first run.

## Migration Steps
1) Build and test locally
   - Ensure you have the needed spaCy model available. Either pre-install the model in the image or set MODEL_DOWNLOAD=true and allow the container to download at startup (slower).
   - Build image: docker build -t your-repo/spacy-featurizer:latest .
   - Run locally: docker run -p 8000:8000 -e MODEL_NAME=en_core_web_sm your-repo/spacy-featurizer:latest

2) Push image to your registry
   - docker tag ... ; docker push ...

3) Deploy to Kubernetes
   - Replace <REPLACE_WITH_YOUR_IMAGE> in kubernetes_manifest with your pushed image.
   - kubectl apply -f k8s-deployment.yaml
   - Monitor: kubectl get pods; kubectl logs -f <pod>

4) Terraform (ECS/EKS)
   - If using ECS/Fargate: create ECR repository, push image, configure task definition with container image, set port 8000, create service.
   - If using EKS: use official modules to create cluster and apply the k8s manifests via CI/CD.

5) Observability
   - Metrics: /metrics exposed for Prometheus scraping. Ensure Prometheus scrape config targets the service.
   - Logging: structured JSON logs printed to stdout. Configure your log aggregator to parse JSON.

6) Scaling
   - Set HPA (HorizontalPodAutoscaler) based on CPU or custom metrics as needed.

7) Secrets
   - Do not store DB passwords in plain env. Use Kubernetes Secrets or AWS Secrets Manager and inject at runtime.

