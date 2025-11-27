# cURL Examples

This directory contains cURL examples for interacting with the bot API.

## Authentication

All API requests require authentication using a Bearer token:

```bash
Authorization: Bearer YOUR_API_KEY
X-Bot-ID: YOUR_BOT_ID
```

## Examples

### 1. Start a Conversation

```bash
curl -X POST http://localhost:8000/api/v2/conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "X-Bot-ID: YOUR_BOT_ID" \
  -d '{"bot_id": "YOUR_BOT_ID"}'
```

Response:
```json
{
  "session_id": "sess_123456",
  "message": "Hello! How can I help you today?"
}
```

### 2. Send a Message

Replace `SESSION_ID` with the session ID from the previous step:

```bash
curl -X POST http://localhost:8000/api/v2/conversations/SESSION_ID/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "X-Bot-ID: YOUR_BOT_ID" \
  -d '{"message": "What is my order status?"}'
```

Response:
```json
{
  "message": "I can help you check your order status. Please provide your order number.",
  "intent": "check_order_status",
  "confidence": 0.95
}
```

### 3. Get Conversation History

```bash
curl -X GET http://localhost:8000/api/v2/conversations/SESSION_ID \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "X-Bot-ID: YOUR_BOT_ID"
```

Response:
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
    },
    {
      "role": "bot",
      "message": "I can help you check your order status. Please provide your order number."
    }
  ]
}
```

## Environment Variables

Set these environment variables for easier usage:

```bash
export API_KEY="your-api-key"
export BOT_ID="your-bot-id"
export API_URL="http://localhost:8000"
```

Then use them in commands:

```bash
curl -X POST $API_URL/api/v2/conversations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Bot-ID: $BOT_ID" \
  -d '{"bot_id": "'$BOT_ID'"}'
```