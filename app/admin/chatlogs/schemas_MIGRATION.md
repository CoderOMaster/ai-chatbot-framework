# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/admin/chatlogs/schemas.py
- Deployment: Lambda
- Complexity: Low
- Estimated Hours: 4

## Breaking Changes
- The Lambda handler expects API Gateway proxy events (httpMethod, path, pathParameters). Integration must be configured accordingly.
- ChatLog storage now requires a 'thread_id' to be provided in the POST payload; original ChatLog model did not include thread_id.
- Mutable default dicts on ChatMessage.context and ChatLog.context were fixed to use Field(default_factory=dict).
- Filesystem usage removed: persistence moved to DynamoDB (CHAT_TABLE_NAME). If you previously relied on local filesystem, you must migrate to DynamoDB or S3.
- Spelling and class names from original code were preserved (BotNessage remains). However the storage schema includes 'thread_id' and 'date' keys used as partition/sort keys in DynamoDB.
- API responses are API Gateway proxy compatible; callers must handle JSON response envelope {statusCode, headers, body}.

## Migration Steps
1. Create the DynamoDB table
   - Table name: set via environment variable CHAT_TABLE_NAME (default: chat-logs-table)
   - Recommended keys: partition key 'thread_id' (String), sort key 'date' (String - ISO8601). This enables efficient Query by thread_id.

2. Package the Lambda
   - Include schemas.py and its dependencies. Pydantic is required. You can either:
     a) Bundle pydantic into the deployment package (recommended for simplicity), or
     b) Provide an AWS Lambda Layer that contains pydantic.

3. Set environment variables in Lambda configuration
   - CHAT_TABLE_NAME, AWS_REGION, LOG_LEVEL, TIMEOUT_BUFFER_MS (optional)

4. Ensure IAM permissions
   - Attach a policy allowing dynamodb:PutItem, dynamodb:Query, dynamodb:Scan, dynamodb:GetItem on the target table
   - Lambda needs CloudWatch Logs permissions (CreateLogGroup/CreateLogStream/PutLogEvents)

5. Deploy API Gateway
   - Use the included Terraform to create a proxy integration, or configure a REST API with routes:
     POST /logs, GET /threads, GET /logs/{thread_id}

6. Testing
   - POST /logs with JSON body: { "thread_id": "thread1", "user_message": {"text":"hi"}, "bot_message": [{"text":"hello"}], "date": "2025-01-01T12:00:00Z" }
   - GET /threads to list threads
   - GET /logs/thread1 to fetch logs for thread1

7. Operational notes
   - The code uses table scans for thread listing; for production, maintain a separate threads table or a GSI to avoid expensive scans.
   - Ensure deployment package size is within Lambda limits when bundling pydantic.

