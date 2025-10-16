# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/nlu/intent_classifiers/sklearn_intent_classifer.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 24

## Breaking Changes
- API surface: Replaces original Python class file with a FastAPI microservice exposing /predict, /health, and /readiness endpoints; code that previously imported and instantiated SklearnIntentClassifier must adapt to calling HTTP endpoints or import the class from the new module.
- Input format: /predict accepts raw text (JSON {"text": "..."}). The service builds spaCy docs internally. The original component expected spaCy docs in-memory; if you integrate the class directly, ensure spaCy doc objects are provided.
- Model loading: Model path is now configured via MODEL_DIR and model name via MODEL_NAME environment variables instead of passing arbitrary paths to load(); service behavior assumes the model is present in MODEL_DIR on startup or accessible to the container.
- Logging: Logs are now JSON-structured; consumers expecting plain text logs will need adaptation.
- Runtime packaging: The service expects spaCy model weights to be available (SPACY_MODEL). Including spaCy models in the image may increase size significantly.
- Dependency changes: Additional dependencies (FastAPI, uvicorn, prometheus_client, SQLAlchemy, python-json-logger) were introduced and must be installed in runtime.

## Migration Steps
1) Build and bake the model: Train offline and save the trained model using cloudpickle as 'sklearn_intent_model.hd5' in /app/models inside the image or upload to a model registry/S3 and download at startup.

2) Build the container image:
   - docker build -t <registry>/sklearn-intent-classifier:latest .
   - Push to your container registry.

3) Provide spaCy model weights:
   - Either include the spaCy model wheel in the image or ensure the container can download it on startup (e.g. via a startup script) and that the model is present under the name provided by SPACY_MODEL.
   - Example: python -m spacy download en_core_web_md (note: this increases image size).

4) Kubernetes deployment:
   - Update the image in the k8s manifest and apply: kubectl apply -f deployment.yaml
   - Ensure the MODEL_DIR (or a mounted volume) contains the trained model file or that the container can fetch it at startup.

5) ECS Fargate (if using Terraform):
   - Populate Terraform variables (image, subnets, security groups) and apply.

6) Logging & Monitoring:
   - Logs are emitted as structured JSON; configure your logging pipeline (FluentD/FluentBit/CloudWatch) to capture container stdout.
   - Expose Prometheus metrics (/metrics) to your monitoring stack.

7) Readiness/Liveness:
   - The service implements /health and /readiness endpoints.
   - The readiness probe will fail until the model and spaCy are available (or readiness file is present).

8) Graceful shutdown:
   - The container handles SIGTERM and will run cleanup tasks, close DB pools and unmark readiness.

9) Database:
   - If you need DB access, provide DB_URL; connection pool is initialized by SQLAlchemy.

10) Secrets:
   - Use your platform's secrets manager for DB credentials and model registry access tokens. Do not bake secrets into the image.

