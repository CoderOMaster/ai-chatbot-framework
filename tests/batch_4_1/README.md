Batch 4.1

Scope
- Dialogue manager HTTP client and core intent processing logic.

Added tests
- test_http_client.py: covers GET/POST/PUT/DELETE flows, JSON vs params, error and timeout mapping to APICallExcetion, and invalid method ValueError.
- test_dialogue_manager_core.py: covers intent id selection (slash commands, threshold fallback, normal), entity-to-parameter matching, free_text prompt handling, missing parameter prompts via split_sentence, cancel flow reset, non-API and API trigger rendering including URL/payload templating and error fallback, and process precondition when NLU pipeline missing.