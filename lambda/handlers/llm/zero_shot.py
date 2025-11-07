# Compatibility shim delegating to new handler location
from lambda_handlers.llm.zero_shot import handler as _handler


def handler(event, context):  # pragma: no cover - thin delegate
    return _handler(event, context)