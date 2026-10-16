"""Keep Windows subprocess execution available when Uvicorn reload is enabled."""

import asyncio
import sys


def create_event_loop():
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()
