# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/nlu/llm/zero_shot_nlu_openai.py
- Deployment: Microservice
- Complexity: Medium
- Estimated Hours: 16

## Breaking Changes
- The NLU component is now embedded in a FastAPI microservice and expects to be called via the /process endpoint (POST) with the message JSON payload. Previously it was a standalone class used inside a monolith.
- Configuration is via environment variables (OPENAI_BASE_URL, OPENAI_API_KEY, PROMPTS_PATH, etc.) rather than constructor args. Adapt your deployment to set these env vars.
- Template loading now relies on PROMPTS_PATH and PROMPT_FILENAME. Ensure prompt files are present in the container image at the configured path.
- A database connection is optional and will be created only when DATABASE_URL is provided. If your previous runtime held an active DB session differently, update code to use SQLAlchemy pooling or remove DATABASE_URL.
- The service exposes metrics at /metrics. If you previously used another metrics endpoint, update monitoring configuration.
- The code now uses structured JSON logs. Log format has changed and may require updates to log parsers/consumers.

## Migration Steps
1) Build the container image using the provided Dockerfile and push it to your container registry (ECR/GCR/ACR).

2) Ensure the prompt templates are included in the image under the path configured by PROMPTS_PATH (default: app/bot/nlu/llm/prompts). The file ZERO_SHOT_LEARNING_PROMPT.md must be present.

3) Configure environment variables in your deployment platform:
   - OPENAI_BASE_URL: URL to the LLM server (sidecar or remote)
   - OPENAI_API_KEY: API key for the model server (if required)
   - OPENAI_MODEL_NAME: Model name identifier
   - PROMPTS_PATH / PROMPT_FILENAME: path/filename for the prompt template
   - INTENTS / ENTITIES: optional comma-separated lists to seed the prompt
   - DATABASE_URL: optional, if you want DB pooling

4) Deploy on Kubernetes using the provided manifest. Update image names, secrets, and config maps as needed.

5) If using EKS/ECS via Terraform, customize the terraform_config to fit your VPC, subnets, and IAM roles. You'll need to create secrets for API keys.

6) Monitor /metrics for Prometheus metrics and /health and /readiness endpoints for K8s health checks.

7) For graceful shutdown, the container traps SIGTERM and FastAPI lifecycle events will run to dispose of DB connections. Ensure your container orchestration uses graceful termination times (terminationGracePeriodSeconds in K8s) sufficient to allow in-flight requests to finish.

