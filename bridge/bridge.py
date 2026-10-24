"""WebSocket bridge server — entry point.

This is the backward-compatible entry point. The implementation has moved to:
- bridge/server.py       — WebSocket server with protocol routing
- bridge/conversation.py — conversation engine (Haiku, NPC chat)
- bridge/domain_manager.py — domain session orchestration
- bridge/domain_session.py — Agent SDK runtime per domain

D-005: zero UI awareness.
D-033: synchronous NPC response with timeout; D-034: asynchronous domains.
D-015: ws://localhost:8765.
"""

import asyncio
from contextlib import contextmanager, ExitStack
import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.server import serve  # noqa: E402


@contextmanager
def _requested_stop(stop_event):
    """Own CLI signals until drain finishes; embedded callers own their signals."""
    loop = asyncio.get_running_loop()
    with ExitStack() as handlers:
        # Python only permits signal ownership in the main thread. A caller
        # running main() elsewhere keeps its own interruption/cancellation path.
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGINT, signal.SIGTERM):
                previous = signal.getsignal(number)
                using_loop = True
                try:
                    loop.add_signal_handler(number, stop_event.set)
                except NotImplementedError:
                    # Windows event loops lack add_signal_handler. Scheduling
                    # thread-safely also wakes a loop blocked in its IO poll.
                    using_loop = False

                    def request_stop(_number, _frame):
                        loop.call_soon_threadsafe(stop_event.set)

                    signal.signal(number, request_stop)
                handlers.callback(signal.signal, number, previous)
                if using_loop:
                    handlers.callback(loop.remove_signal_handler, number)
        yield


async def _serve_cli():
    stop_event = asyncio.Event()
    with _requested_stop(stop_event):
        await serve(stop_event=stop_event)


def main():
    """Run the CLI in its own loop, retaining handlers through owned cleanup."""
    asyncio.run(_serve_cli())


if __name__ == "__main__":
    main()
