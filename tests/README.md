This folder contains tests for batches up to 4.1.

Coverage highlights
- Batch 1.1: app.common.config.Settings, app.config shim, app.dependencies DialogueManager DI, app.bot.memory.models.State DTO.
- Batch 2.1: app.common.database factories (get_mongo_client/get_db), ping_db health check, database shim behavior, MemorySaverMongo basics.
- Batch 3.1: http_client request building and errors; DialogueManager API failure path.
- Batch 3.2: LLM zero-shot Lambda handler end-to-end with retries and parsing.
- Batch 4.1: Frontend Next.js base URL env wiring, Dockerfile multistage and runtime, docker-compose env, Terraform frontend module.

Running tests
- Python unit tests: pytest -q
- Note: Frontend and Terraform tests are static source checks to validate configuration presence and content.