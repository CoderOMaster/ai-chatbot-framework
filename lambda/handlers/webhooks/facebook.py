# Compatibility shim: define handler and delegate to real implementation
from typing import Any, Dict
from lambda_handlers.webhooks.facebook import handler as _real_handler


def handler(event: Dict[str, Any], context: Any):
    return _real_handler(event, context)