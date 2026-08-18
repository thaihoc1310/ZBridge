import asyncio
from collections.abc import Coroutine
from typing import Any

_event_loop: asyncio.AbstractEventLoop | None = None


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    global _event_loop
    if _event_loop is None or _event_loop.is_closed():
        _event_loop = asyncio.new_event_loop()
    return _event_loop.run_until_complete(coroutine)
