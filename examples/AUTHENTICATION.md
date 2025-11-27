# Authentication Guide

This guide explains how to authenticate with the bot API and manage API keys securely.

## Overview

The bot API uses Bearer token authentication combined with bot ID headers for all requests.

## Authentication Methods

### 1. Bearer Token (Recommended)

All API requests must include an `Authorization` header with a Bearer token:

```
Authorization: Bearer YOUR_API_KEY
```

### 2. Bot ID Header

Additionally, include the bot ID in the `X-Bot-ID` header:

```
X-Bot-ID: YOUR_BOT_ID
```

### Complete Header Example

```
GET /api/v2/conversations/sess_123 HTTP/1.1
Host: api.example.com
Authorization: Bearer sk_live_abc123def456
X-Bot-ID: bot_prod_789
Content-Type: application/json
```

## Getting API Credentials

### Step 1: Access Admin Panel

1. Navigate to `http://localhost:8080` (or your admin URL)
2. Log in with your admin credentials

### Step 2: Generate API Key

1. Go to **Settings** → **API Keys**
2. Click **Create New Key**
3. Enter a descriptive name (e.g., "Production API Key")
4. Select the appropriate permissions:
   - `conversations:read` - Read conversation history
   - `conversations:write` - Send messages
   - `conversations:create` - Start new conversations
5. Click **Generate**
6. **Copy and save** the key immediately (it won't be shown again)

### Step 3: Get Bot ID

1. Go to **Settings** → **Bot Information**
2. Copy your **Bot ID** (format: `bot_xxxxx`)

## Environment Variables

Store credentials as environment variables instead of hardcoding them:

### Linux/macOS

```bash
# Add to ~/.bashrc, ~/.zshrc, or ~/.bash_profile
export BOT_API_KEY="sk_live_abc123def456"
export BOT_ID="bot_prod_789"
export API_BASE_URL="https://api.example.com"
```

### Windows (PowerShell)

```powershell
$env:BOT_API_KEY = "sk_live_abc123def456"
$env:BOT_ID = "bot_prod_789"
$env:API_BASE_URL = "https://api.example.com"
```

### Docker

```dockerfile
ENV BOT_API_KEY=sk_live_abc123def456
ENV BOT_ID=bot_prod_789
ENV API_BASE_URL=https://api.example.com
```

### Docker Compose

```yaml
services:
  app:
    environment:
      BOT_API_KEY: ${BOT_API_KEY}
      BOT_ID: ${BOT_ID}
      API_BASE_URL: https://api.example.com
```

## Secure Storage

### 1. .env Files (Development Only)

Create a `.env` file in your project root:

```
BOT_API_KEY=sk_live_abc123def456
BOT_ID=bot_prod_789
API_BASE_URL=http://localhost:8000
```

**Important**: Add `.env` to `.gitignore`:

```
# .gitignore
.env
.env.local
.env.*.local
```

### 2. AWS Secrets Manager

```python
import boto3

def get_api_credentials():
    client = boto3.client('secretsmanager')
    secret = client.get_secret_value(SecretId='bot-api-credentials')
    return json.loads(secret['SecretString'])

credentials = get_api_credentials()
api_key = credentials['BOT_API_KEY']
bot_id = credentials['BOT_ID']
```

### 3. HashiCorp Vault

```python
import hvac

def get_api_credentials():
    client = hvac.Client(url='http://vault.example.com:8200')
    secret = client.secrets.kv.read_secret_version(path='bot-api')
    return secret['data']['data']

credentials = get_api_credentials()
api_key = credentials['BOT_API_KEY']
bot_id = credentials['BOT_ID']
```

### 4. Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bot-api-credentials
type: Opaque
stringData:
  BOT_API_KEY: sk_live_abc123def456
  BOT_ID: bot_prod_789
```

Access in your pod:

```python
import os

api_key = os.getenv('BOT_API_KEY')
bot_id = os.getenv('BOT_ID')
```

## API Key Management

### Key Rotation

1. Generate a new API key (see "Getting API Credentials")
2. Update your applications to use the new key
3. Wait for all services to update
4. Revoke the old key in **Settings** → **API Keys**

### Key Scopes

Different API keys can have different permissions:

| Scope | Permission | Use Case |
|-------|-----------|----------|
| `conversations:read` | Read-only access | Monitoring, analytics |
| `conversations:write` | Send messages | Chat applications |
| `conversations:create` | Start conversations | New session creation |
| `admin:write` | Full admin access | Admin tools |

### Revoking Keys

1. Go to **Settings** → **API Keys**
2. Find the key to revoke
3. Click **Revoke**
4. Confirm the action

**Note**: Revoking a key immediately invalidates all requests using it.

## Authentication in Code

### Python

```python
import os
import requests

api_key = os.getenv('BOT_API_KEY')
bot_id = os.getenv('BOT_ID')

headers = {
    'Authorization': f'Bearer {api_key}',
    'X-Bot-ID': bot_id,
    'Content-Type': 'application/json'
}

response = requests.post(
    'http://localhost:8000/api/v2/conversations',
    json={'bot_id': bot_id},
    headers=headers
)
```

### Node.js

```javascript
const axios = require('axios');

const apiKey = process.env.BOT_API_KEY;
const botId = process.env.BOT_ID;

const client = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    'Authorization': `Bearer ${apiKey}`,
    'X-Bot-ID': botId,
    'Content-Type': 'application/json'
  }
});

client.post('/api/v2/conversations', { bot_id: botId });
```

### Go

```go
package main

import (
    "fmt"
    "net/http"
    "os"
)

func main() {
    apiKey := os.Getenv("BOT_API_KEY")
    botId := os.Getenv("BOT_ID")

    req, _ := http.NewRequest("POST", "http://localhost:8000/api/v2/conversations", nil)
    req.Header.Add("Authorization", fmt.Sprintf("Bearer %s", apiKey))
    req.Header.Add("X-Bot-ID", botId)
    req.Header.Add("Content-Type", "application/json")

    client := &http.Client{}
    client.Do(req)
}
```

### Java

```java
import java.net.http.HttpRequest;

String apiKey = System.getenv("BOT_API_KEY");
String botId = System.getenv("BOT_ID");

HttpRequest request = HttpRequest.newBuilder()
    .uri(URI.create("http://localhost:8000/api/v2/conversations"))
    .header("Authorization", "Bearer " + apiKey)
    .header("X-Bot-ID", botId)
    .header("Content-Type", "application/json")
    .POST(HttpRequest.BodyPublishers.ofString("{}"))
    .build();
```

## Error Handling

### 401 Unauthorized

**Cause**: Invalid or missing API key

**Solution**:
1. Verify the API key is correct
2. Check that the key hasn't been revoked
3. Ensure the key is passed in the `Authorization` header

### 403 Forbidden

**Cause**: API key lacks required permissions

**Solution**:
1. Generate a new key with appropriate scopes
2. Or request elevated permissions from an admin

### 429 Too Many Requests

**Cause**: Rate limit exceeded

**Solution**:
1. Implement exponential backoff
2. Request higher rate limits from support
3. Cache responses when possible

## Best Practices

1. **Never commit credentials**: Use `.gitignore` and environment variables
2. **Rotate keys regularly**: Rotate API keys every 90 days
3. **Use minimal scopes**: Only grant necessary permissions
4. **Monitor key usage**: Check API key activity logs
5. **Revoke unused keys**: Clean up old or unused keys
6. **Use HTTPS**: Always use HTTPS in production
7. **Implement timeouts**: Set reasonable request timeouts
8. **Log authentication failures**: Monitor for suspicious activity

## Troubleshooting

### "Invalid API Key"

- Verify the key is correct (no extra spaces)
- Check the key hasn't expired or been revoked
- Generate a new key if needed

### "Missing X-Bot-ID Header"

- Ensure the `X-Bot-ID` header is included
- Verify the bot ID is correct

### "Rate Limited"

- Implement exponential backoff
- Reduce request frequency
- Contact support for higher limits

## Support

For authentication issues:

1. Check this guide
2. Review the [API documentation](../docs/)
3. Contact support@example.com