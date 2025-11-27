# Quick Start Guide

Get up and running with the bot API in 5 minutes.

## Prerequisites

- API credentials (see [Authentication Guide](AUTHENTICATION.md))
- Your preferred programming language installed
- `curl` or Postman (optional, for testing)

## Step 1: Get Your Credentials

1. Access the admin panel at `http://localhost:8080`
2. Go to **Settings** → **API Keys** and create a new key
3. Go to **Settings** → **Bot Information** and copy your Bot ID
4. Set environment variables:

```bash
export BOT_API_KEY="your-api-key"
export BOT_ID="your-bot-id"
export API_BASE_URL="http://localhost:8000"
```

## Step 2: Test with cURL

Start a conversation:

```bash
curl -X POST $API_BASE_URL/api/v2/conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $BOT_API_KEY" \
  -H "X-Bot-ID: $BOT_ID" \
  -d '{"bot_id": "'$BOT_ID'"}'
```

Response:
```json
{
  "session_id": "sess_abc123",
  "message": "Hello! How can I help you?"
}
```

Send a message (replace `SESSION_ID` with the session ID from above):

```bash
curl -X POST $API_BASE_URL/api/v2/conversations/SESSION_ID/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $BOT_API_KEY" \
  -H "X-Bot-ID: $BOT_ID" \
  -d '{"message": "Hello!"}'
```

## Step 3: Choose Your Language

### Python

```bash
cd examples/python
pip install requests
python app.py
```

### Node.js

```bash
cd examples/nodejs
npm install discord.js axios
node discordRequest.js
```

### Go

```bash
cd examples/go
go run main.go
```

### Java

```bash
cd examples/java
javac -cp ".:gson-2.10.1.jar" BotClient.java
java -cp ".:gson-2.10.1.jar" BotClient
```

## Step 4: Integrate into Your Application

### Python Integration

```python
from examples.python.app import BotClient

client = BotClient("http://localhost:8000", "your-api-key", "your-bot-id")
client.start_conversation()
response = client.send_message("What is my order status?")
print(response.get("message"))
```

### Node.js Integration

```javascript
const botIntegration = require('./examples/nodejs/discordRequest');

const botClient = botIntegration.initializeBotClient();
await botClient.startConversation();
const response = await botClient.sendMessage("What is my order status?");
console.log(response.message);
```

### Go Integration

```go
import "examples/go"

client := NewBotClient("http://localhost:8000", "your-api-key", "your-bot-id")
client.StartConversation()
client.SendMessage("What is my order status?")
```

### Java Integration

```java
import examples.java.BotClient;

BotClient client = new BotClient("http://localhost:8000", "your-api-key", "your-bot-id");
client.startConversation();
JsonObject response = client.sendMessage("What is my order status?");
```

## Common Tasks

### 1. Start a Conversation

```python
client = BotClient(api_url, api_key, bot_id)
response = client.start_conversation()
print(response.get("message"))  # Bot's welcome message
```

### 2. Send a Message

```python
response = client.send_message("Hello, bot!")
print(response.get("message"))  # Bot's response
```

### 3. Get Conversation History

```python
history = client.get_conversation_history()
for msg in history.get("messages", []):
    print(f"{msg['role']}: {msg['message']}")
```

### 4. Handle Errors

```python
try:
    response = client.send_message("Hello")
except requests.exceptions.RequestException as e:
    print(f"Error: {e}")
```

## Next Steps

1. **Read the full documentation**: See [README.md](README.md)
2. **Learn authentication**: See [AUTHENTICATION.md](AUTHENTICATION.md)
3. **Explore use cases**: Check language-specific examples
4. **Deploy to production**: See deployment guides in [docs/](../docs/)

## Troubleshooting

### "401 Unauthorized"

- Check your API key is correct
- Verify the `Authorization` header is set
- Ensure the key hasn't been revoked

### "404 Not Found"

- Verify the session ID is correct
- Check the API URL is correct

### "Connection Refused"

- Ensure the API server is running
- Check the API URL in your configuration

## Support

- **Documentation**: [docs/](../docs/)
- **Issues**: GitHub Issues
- **Email**: support@example.com

## What's Next?

- [Create your first bot](../docs/02-getting-started.md)
- [Integrate with channels](../docs/04-integrating-with-channels.md)
- [Deploy to production](../docs/DEPLOYMENT.md)