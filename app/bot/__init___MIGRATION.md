# Migration Guide

## File Info
- Original: ai-chatbot-framework/app/bot/__init__.py
- Deployment: Lambda
- Complexity: Low
- Estimated Hours: 2

## Breaking Changes
- No filesystem access: The refactored handler does not read/write local filesystem. Use S3 and DynamoDB for persistence.
- Configuration moved to environment variables: BUCKET_NAME, TABLE_NAME, REGION, DEFAULT_KEY, LOG_LEVEL are required/used instead of hard-coded values.
- Structured logging: prints replaced with structured JSON logs; log formats/fields changed.
- API Gateway response format: The handler returns API Gateway compatible responses (statusCode, headers, body) instead of raw values/prints.
- Timeout handling: Function checks remaining time and can return 504 if there isn't enough time to complete operations.
- Initialization moved to cold-start scope: boto3 clients/resources initialized outside the handler for performance; ensure IAM permissions allow those actions.

## Migration Steps
1) Set required environment variables in the Lambda configuration: BUCKET_NAME, TABLE_NAME (optional), REGION, DEFAULT_KEY, LOG_LEVEL.
2) Ensure the Lambda execution role has permissions: s3:GetObject, s3:PutObject on the configured bucket; dynamodb:GetItem, dynamodb:PutItem on the configured table; and CloudWatch Logs permissions.
3) Package the code (ensure __init__.py is at the root of the zip) and deploy via Terraform or AWS Console. If using layers, include boto3/botocore layers only if you need custom versions (builtin boto3 is available in Lambda runtime).
4) Create API Gateway and integrate with the Lambda function (example Terraform provided).
5) Test GET via: GET /?key=your-key -> returns DynamoDB item or S3 object fallback.
6) Test POST by sending JSON body with 'id' and optional 's3_key' to store both in DynamoDB and S3.
7) Monitor CloudWatch logs. The logs are structured JSON for easier querying in CloudWatch Logs Insights.
8) Tune TIMEOUT_SAFETY_MS environment variable if you have operations that need more buffer time before Lambda's timeout.


