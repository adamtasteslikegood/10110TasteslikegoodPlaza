"""WebSocket bridge server — entry point.

This is the backward-compatible entry point. The implementation has moved to:
- bridge/server.py       — WebSocket server with protocol routing
- bridge/conversation.py — conversation engine (Haiku, NPC chat)
- bridge/domain_manager.py — domain session orchestration
- bridge/domain_session.py — Agent SDK runtime per domain

D-005: zero UI awareness.
D-006: synchronous with timeout (conversation engine).
D-015: ws://localhost:8765.
"""

import asyncio

from bridge.server import serve

if __name__ == "__main__":
    asyncio.run(serve())
