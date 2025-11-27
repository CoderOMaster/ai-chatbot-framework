# Bot API Examples

This directory contains examples of how to integrate with the bot API using various programming languages and frameworks.

## Table of Contents

- [Authentication](#authentication)
- [API Endpoints](#api-endpoints)
- [Language Examples](#language-examples)
- [Common Use Cases](#common-use-cases)
- [Error Handling](#error-handling)

## Authentication

All API requests require authentication using a Bearer token and bot ID:

```
Authorization: Bearer YOUR_API_KEY
X-Bot-ID: YOUR_BOT_ID
```

### Getting Your Credentials

1. **API Key**: Generate from the admin panel under Settings → API Keys
2. **Bot ID**: Found in the admin panel under Settings → Bot Information

### Environment Variables

Set these for easier development:

```bash
export BOT_API_KEY="your-api-key"
export BOT_ID="your-bot-id"
export API_BASE_URL="http://localhost:8000"  # or your production URL
```

## API Endpoints

### Start a Conversation

**Endpoint**: `POST /api/v2/conversations`

**Request**:
```json
{
  "bot_id": "your-bot-id"
}
```

**Response**:
```json
{
  "session_id": "sess_123456",
  "message": "Hello! How can I help you today?"
}
```

### Send a Message

**Endpoint**: `POST /api/v2/conversations/{session_id}/messages`

**Request**:
```json
{
  "message": "What is my order status?"
}
```

**Response**:
```json
{
  "message": "I can help you check your order status. Please provide your order number.",
  "intent": "check_order_status",
  "confidence": 0.95,
  "entities": {
    "order_number": null
  }
}
```

### Get Conversation History

**Endpoint**: `GET /api/v2/conversations/{session_id}`

**Response**:
```json
{
  "session_id": "sess_123456",
  "messages": [
    {
      "role": "bot",
      "message": "Hello! How can I help you today?"
    },
    {
      "role": "user",
      "message": "What is my order status?"
    }
  ]
}
```

## Language Examples

### Python

The Python example demonstrates:
- Basic authentication
- Starting conversations
- Sending and receiving messages
- Error handling
- Type hints and documentation

**File**: `python/app.py`

**Requirements**:
```bash
pip install requests
```

**Usage**:
```bash
cd python
export BOT_API_KEY="your-key"
export BOT_ID="your-bot-id"
python app.py
```

### Node.js

The Node.js example demonstrates:
- Discord bot integration
- Async/await patterns
- Environment variable configuration
- Error handling

**File**: `nodejs/discordRequest.js`

**Requirements**:
```bash
npm install discord.js axios
```

**Usage**:
```javascript
const botIntegration = require('./discordRequest');
const botClient = botIntegration.initializeBotClient();
await botClient.startConversation();
```

### Go

The Go example demonstrates:
- HTTP client usage
- JSON marshaling/unmarshaling
- Interactive CLI
- Structured error handling

**File**: `go/main.go`

**Requirements**:
- Go 1.16+

**Usage**:
```bash
cd go
export BOT_API_KEY="your-key"
export BOT_ID="your-bot-id"
go run main.go
```

### Java

The Java example demonstrates:
- Java 11+ HTTP client
- Gson for JSON handling
- Object-oriented design
- Exception handling

**File**: `java/BotClient.java`

**Requirements**:
- Java 11+
- Gson library

**Maven dependency**:
```xml
<dependency>
    <groupId>com.google.code.gson</groupId>
    <artifactId>gson</artifactId>
    <version>2.10.1</version>
</dependency>
```

**Usage**:
```bash
cd java
javac -cp ".:gson-2.10.1.jar" BotClient.java
java -cp ".:gson-2.10.1.jar" BotClient
```

### cURL

The cURL examples demonstrate:
- Basic HTTP requests
- Header configuration
- JSON payloads
- Environment variable usage

**File**: `curl/README.md`

**Usage**:
```bash
curl -X POST http://localhost:8000/api/v2/conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "X-Bot-ID: YOUR_BOT_ID" \
  -d '{"bot_id": "YOUR_BOT_ID"}'
```

## Common Use Cases

### 1. Order Status Check

```python
client = BotClient(API_BASE_URL, API_KEY, BOT_ID)
client.start_conversation()
response = client.send_message("What is my order status?")
# Bot will ask for order number
response = client.send_message("ORD123456")
# Bot will return order status
```

### 2. FAQ Bot

```javascript
const botClient = botIntegration.initializeBotClient();
await botClient.startConversation();
const response = await botClient.sendMessage("How do I reset my password?");
```

### 3. Multi-turn Conversation

```go
client := NewBotClient(apiURL, apiKey, botID)
client.StartConversation()
client.SendMessage("I want to book a table")
client.SendMessage("For 4 people")
client.SendMessage("At 7 PM")
```

### 4. Batch Processing

```java
BotClient client = new BotClient(apiUrl, apiKey, botId);
client.startConversation();

List<String> messages = Arrays.asList(
    "What are your business hours?",
    "Do you have vegetarian options?",
    "Can I make a reservation?"
);

for (String message : messages) {
    JsonObject response = client.sendMessage(message);
    System.out.println(response.get("message").getAsString());
}
```

## Error Handling

### Common Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 401 | Unauthorized | Check your API key and bot ID |
| 404 | Not Found | Verify the session ID is correct |
| 429 | Rate Limited | Implement exponential backoff |
| 500 | Server Error | Check server logs and retry |

### Retry Strategy

All examples implement exponential backoff for retries:

```python
import time

def send_with_retry(client, message, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.send_message(message)
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            else:
                raise
```

## Best Practices

1. **Store credentials securely**: Use environment variables or secure vaults
2. **Implement timeouts**: Set reasonable timeouts for API calls
3. **Handle errors gracefully**: Implement retry logic with exponential backoff
4. **Log interactions**: Keep logs for debugging and auditing
5. **Test locally first**: Use `http://localhost:8000` for development
6. **Monitor rate limits**: Implement rate limit handling
7. **Use session IDs**: Reuse session IDs for multi-turn conversations

## Deployment

### Docker

Each language example can be containerized:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

### Lambda Functions

For AWS Lambda integration, see the Lambda-specific examples in the `lambda/` directory.

### Microservices

For microservice integration patterns, see the `microservices/` directory.

## Support

For issues or questions:

1. Check the [documentation](../docs/)
2. Review the [troubleshooting guide](../docs/TROUBLESHOOTING.md)
3. Open an issue on GitHub
4. Contact support@example.com

## License

These examples are provided under the same license as the main project.