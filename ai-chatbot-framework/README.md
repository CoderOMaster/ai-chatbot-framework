Core API service (FastAPI)

- Uses FastAPI lifespan to initialize DialogueManager and close DB clients.
- Readiness: /ready returns 200 when service is up (ALB health). Liveness: /live.
- Configure remote NLU inference via MODEL_FORWARDING_ENDPOINT to offload heavy model work to nlu-runtime.

Build and run locally

- docker-compose -f ai-chatbot-framework/docker-compose.core.yml up --build core-api

Environment

- MONGODB_HOST, MONGODB_DATABASE
- MODEL_FORWARDING_ENDPOINT (e.g., http://nlu-runtime:8001/predict)
- JWT_SECRET