# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/channels/facebook/messenger.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 16

## Breaking Changes
- Exposed public HTTP API endpoints and altered initialization: the module is now a FastAPI application (messenger_service:app) and must be run with an ASGI server (uvicorn).
- Configuration is now via environment variables (PAGE_ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN, DB_DSN). The original code's constructor-based injection is preserved but wiring is now done in startup events.
- HTTP client session is pooled and shared across requests; FacebookSender now requires a session rather than creating a new one per request.
- DialogueManager is instantiated at startup and (optionally) receives a db_pool argument; ensure the DialogueManager constructor accepts db_pool or adapt accordingly.
- Webhook signature header handling supports both 'X-Hub-Signature' and 'X-Hub-Signature-256'. If you previously relied on a different header name, update the caller.
- Return values and error handling are now through FastAPI/HTTPException rather than raising exceptions within background tasks; this affects how errors are surfaced in logs and status codes.

## Migration Steps
1) Build and publish container image: update <YOUR_REGISTRY> in k8s manifest. Use the provided Dockerfile and requirements.txt to build an optimized image.
2) Create Kubernetes Secrets for FB tokens and DB DSN (kubectl create secret generic fb-secrets --from-literal=page_access_token=... --from-literal=app_secret=... --from-literal=verify_token=...)
3) Apply the Kubernetes manifest (kubectl apply -f k8s_manifest.yaml). Adjust imagePullSecrets and resource requests/limits as needed.
4) If deploying to ECS/Fargate, adapt the Terraform template with VPC, subnets, security groups, and proper IAM roles. Fill variables and run terraform apply.
5) Monitor logs (structured JSON) and metrics (/metrics endpoint) to ensure lifecycle and signature validation are working.
6) For local development, set environment variables and run uvicorn messenger_service:app --reload

Notes about DB pooling: The service uses asyncpg.create_pool with DB_DSN; ensure network connectivity and correct connection limits if deploying many replicas.

