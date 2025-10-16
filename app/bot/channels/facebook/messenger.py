import os
import sys
import asyncio
import signal
import json
import logging
import hashlib
import hmac
from typing import Dict, Any, List, Optional

import aiohttp
import asyncpg
from fastapi import FastAPI, Request, HTTPException, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# Internal imports (unchanged logic)
from app.bot.dialogue_manager.models import UserMessage
from app.bot.dialogue_manager.dialogue_manager import DialogueManager

# Configuration via environment variables
PAGE_ACCESS_TOKEN = os.getenv('PAGE_ACCESS_TOKEN', '')
APP_SECRET = os.getenv('APP_SECRET', '')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN', 'verify_token')
DB_DSN = os.getenv('DB_DSN', '')  # e.g. postgres://user:pass@host:5432/dbname
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
PORT = int(os.getenv('PORT', '8000'))
HOST = os.getenv('HOST', '0.0.0.0')

FACEBOOK_API_URL = 'https://graph.facebook.com/v18.0/me/messages'

# Prometheus metrics
MSG_RECEIVED = Counter('facebook_messages_received_total', 'Total facebook messages received')
MSG_PROCESSED = Counter('facebook_messages_processed_total', 'Total facebook messages processed')
MSG_ERRORS = Counter('facebook_messages_errors_total', 'Total facebook processing errors')

# Structured JSON logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(payload)

logger = logging.getLogger('messenger_service')
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(LOG_LEVEL)
ch.setFormatter(JsonFormatter())
logger.addHandler(ch)
logger.setLevel(LOG_LEVEL)

# FastAPI app
app = FastAPI(title='Facebook Messenger Adapter')

# Global resources
http_client: Optional[aiohttp.ClientSession] = None
db_pool: Optional[asyncpg.pool.Pool] = None
dialogue_manager: Optional[DialogueManager] = None
facebook_sender: Optional['FacebookSender'] = None
shutdown_event = asyncio.Event()


class WebhookVerificationParams(BaseModel):
    'Model for GET verification query params'
    hub_mode: Optional[str] = None
    hub_verify_token: Optional[str] = None
    hub_challenge: Optional[str] = None


class FacebookSender:
    """Handles sending messages to Facebook Messenger using a shared aiohttp session."""

    def __init__(self, access_token: str, session: aiohttp.ClientSession):
        self.access_token = access_token
        self.session = session

    async def send_message(self, recipient_id: str, message: Dict[str, Any]):
        payload = {'recipient': {'id': recipient_id}, 'message': message}
        params = {'access_token': self.access_token}
        async with self.session.post(FACEBOOK_API_URL, json=payload, params=params) as response:
            text = await response.text()
            if response.status != 200:
                try:
                    error_data = json.loads(text)
                except Exception:
                    error_data = {'raw': text}
                logger.error('Error sending message to Facebook', extra={'error': error_data})
                raise HTTPException(status_code=500, detail='Failed to send message to Facebook')
            try:
                return json.loads(text)
            except Exception:
                return {'result': text}

    def format_bot_response(self, bot_message: Dict[str, Any]) -> List[Dict[str, Any]]:
        # preserve original formatting behavior
        messages = [bot_message]
        return messages


class FacebookReceiver:
    """Receives webhook payloads from Facebook and routes them to the DialogueManager."""

    def __init__(self, config: Dict[str, Any], dialogue_manager: DialogueManager, sender: FacebookSender):
        self.config = config
        self.dialogue_manager = dialogue_manager
        self.sender = sender

    def validate_hub_signature(self, request_payload: bytes, hub_signature_header: Optional[str]) -> bool:
        """Validate the request signature from Facebook. Supports 'sha1' and 'sha256' formats like 'sha1=...' or 'sha256=...'."""
        if not hub_signature_header:
            return False
        try:
            method, hub_signature = hub_signature_header.split('=', 1)
            digest_module = getattr(hashlib, method)
            key = bytearray(self.config.get('secret', ''), 'utf8')
            hmac_object = hmac.new(key, request_payload, digest_module)
            generated_hash = hmac_object.hexdigest()
            return hmac.compare_digest(hub_signature, generated_hash)
        except Exception:
            return False

    async def handle_message(self, sender_id: str, message_text: str, context: Dict[str, Any]) -> None:
        user_message = UserMessage(thread_id=sender_id, text=message_text, context=context or {})
        # call dialogue manager - preserve original async behavior
        new_state = await self.dialogue_manager.process(user_message)

        for message in new_state.bot_message:
            formatted_messages = self.sender.format_bot_response(message)
            for formatted_message in formatted_messages:
                await self.sender.send_message(sender_id, formatted_message)

    async def process_webhook_event(self, data: Dict[str, Any]) -> None:
        # Process each entry in the webhook payload
        for entry in data.get('entry', []):
            page_id = entry.get('id')
            for messaging_event in entry.get('messaging', []):
                await self.process_messaging_event(messaging_event, page_id)

    async def process_messaging_event(self, event: Dict[str, Any], page_id: str) -> None:
        sender_id = event.get('sender', {}).get('id')
        if not sender_id:
            return

        if event.get('message') and 'text' in event['message']:
            await self.handle_message(
                sender_id,
                event['message']['text'],
                {
                    'channel': 'facebook',
                    'page_id': page_id,
                    'timestamp': event.get('timestamp'),
                },
            )
        elif event.get('postback'):
            await self.handle_message(
                sender_id,
                event['postback']['payload'],
                {
                    'channel': 'facebook',
                    'page_id': page_id,
                    'timestamp': event.get('timestamp'),
                    'is_postback': True,
                },
            )


@app.on_event('startup')
async def startup_event():
    global http_client, db_pool, dialogue_manager, facebook_sender

    logger.info('Starting up messenger service')

    # aiohttp session reused for connection pooling
    http_client = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        connector=aiohttp.TCPConnector(limit_per_host=20),
    )

    # DB pool (Postgres example). If DB_DSN not provided, skip pool creation.
    if DB_DSN:
        try:
            db_pool = await asyncpg.create_pool(dsn=DB_DSN, min_size=1, max_size=10)
            logger.info('Database connection pool created')
        except Exception as e:
            logger.error('Failed to create DB pool', extra={'error': str(e)})
            raise
    else:
        logger.info('No DB_DSN provided; skipping DB pool creation')

    # Instantiate DialogueManager (may load heavy models internally)
    try:
        # Provide db_pool to DialogueManager if it supports DB usage (adapt as needed)
        dialogue_manager = DialogueManager(db_pool=db_pool) if db_pool else DialogueManager()
        logger.info('DialogueManager initialized')
    except Exception as e:
        logger.error('Failed to initialize DialogueManager', extra={'error': str(e)})
        raise

    # Global Facebook sender/receiver
    facebook_sender = FacebookSender(PAGE_ACCESS_TOKEN, http_client)
    # Register signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_signal_shutdown(s)))
        except NotImplementedError:
            # Not supported on Windows event loop
            pass


async def _signal_shutdown(sig):
    logger.info('Received signal for shutdown', extra={'signal': str(sig)})
    shutdown_event.set()
    # trigger FastAPI shutdown
    await shutdown()


@app.on_event('shutdown')
async def shutdown():
    global http_client, db_pool
    logger.info('Shutting down messenger service')
    if http_client:
        await http_client.close()
        logger.info('HTTP client session closed')
    if db_pool:
        await db_pool.close()
        logger.info('DB pool closed')


@app.get('/health')
async def health():
    return JSONResponse({'status': 'ok'})


@app.get('/readiness')
async def readiness():
    # Basic readiness checks — ensure dialogue_manager and http_client are available
    ready = True
    reasons: List[str] = []
    if not dialogue_manager:
        ready = False
        reasons.append('dialogue_manager_uninitialized')
    if not http_client:
        ready = False
        reasons.append('http_client_uninitialized')
    status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    payload = {'ready': ready, 'reasons': reasons}
    return JSONResponse(payload, status_code=status_code)


@app.get('/metrics')
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get('/webhook')
async def webhook_verify(request: Request):
    # Facebook webhook verification using query params
    params = request.query_params
    mode = params.get('hub.mode') or params.get('hub_mode')
    token = params.get('hub.verify_token') or params.get('hub_verify_token')
    challenge = params.get('hub.challenge') or params.get('hub_challenge')
    logger.info('Received webhook verification request', extra={'mode': mode})
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or '', status_code=200)
    else:
        return PlainTextResponse('Forbidden', status_code=403)


@app.post('/webhook')
async def webhook_receive(request: Request):
    global facebook_sender, dialogue_manager
    try:
        raw_body = await request.body()
        headers = request.headers
        # check signature
        signature = headers.get('X-Hub-Signature-256') or headers.get('X-Hub-Signature')

        receiver_config = {'secret': APP_SECRET}
        receiver = FacebookReceiver(receiver_config, dialogue_manager, facebook_sender)

        if APP_SECRET:
            if not receiver.validate_hub_signature(raw_body, signature):
                logger.warning('Invalid hub signature', extra={'signature': signature})
                MSG_ERRORS.inc()
                raise HTTPException(status_code=403, detail='Invalid signature')

        payload = await request.json()
        MSG_RECEIVED.inc()

        # Process webhook events asynchronously but wait for results to return status.
        await receiver.process_webhook_event(payload)
        MSG_PROCESSED.inc()

        return JSONResponse({'status': 'processed'})
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error('Error processing webhook', extra={'error': str(e)})
        MSG_ERRORS.inc()
        raise HTTPException(status_code=500, detail='Internal error')


# Expose a simple endpoint to demonstrate DB connection pooling usage
@app.get('/db/ping')
async def db_ping():
    if not db_pool:
        return JSONResponse({'db': 'disabled'}, status_code=200)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute('SELECT 1')
        return JSONResponse({'db': 'ok'}, status_code=200)
    except Exception as e:
        logger.error('DB ping failed', extra={'error': str(e)})
        return JSONResponse({'db': 'error', 'detail': str(e)}, status_code=500)


# If run directly, start with uvicorn
if __name__ == '__main__':
    import uvicorn

    uvicorn.run('messenger_service:app', host=HOST, port=PORT, log_level=LOG_LEVEL.lower())
