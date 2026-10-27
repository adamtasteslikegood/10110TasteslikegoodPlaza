"""Offline child used only by SIGKILL crash tests; never contact a provider."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
from uuid import uuid4

from bridge.config import default_config
from bridge.project_service import ProjectService
from bridge.server import BridgeServer
from bridge.state_coordinator import LazySQLiteStateRepository
from bridge.state_image import StateImage
from bridge.tests.domain_fakes import FakeOwner, context


async def main():
    root, runtime, boundary, signal = sys.argv[1:5]
    domain = sys.argv[5] if len(sys.argv) > 5 else "engineering"
    calls = []

    def stop(packet=None):
        Path(signal).write_text(
            json.dumps(dict(boundary=boundary, calls=calls, packet=packet))
        )
        threading.Event().wait()

    original_manifest = StateImage._write_manifest
    original_replace = StateImage._replace
    original_apply = LazySQLiteStateRepository.apply

    def manifest(self, state):
        original_manifest(self, state)
        if boundary == "initializing_manifest" and state == "initializing":
            stop()

    def image(self, name, data):
        original_replace(self, name, data)
        if boundary == "image_before_ready" and name == "state.sqlite3":
            stop()

    def apply(self, command):
        if (boundary == "notes_pending_before_accept" and command.kind == "accept") or (
            boundary == "notes_complete_before_terminal" and command.kind == "terminal"
        ):
            stop()
        result = original_apply(self, command)
        if (
            (boundary == "accepted_before_dispatch" and command.kind == "accept")
            or (boundary == "dispatch_before_sdk" and command.kind == "dispatch")
            or (
                boundary == "terminal_commit_before_delivery"
                and command.kind == "terminal"
            )
        ):
            stop(result.result.get("terminal"))
        return result

    class OfflineOwner(FakeOwner):
        async def execute(self, **kwargs):
            calls.append("execute")
            return await super().execute(**kwargs)

    async def no_provider(*args, **kwargs):
        raise AssertionError("Provider transport is forbidden in crash tests")

    import bridge.domain_session
    from bridge.conversation_api import MessagesAPIBackend
    from bridge.conversation_sdk import ClaudeCodeBackend

    bridge.domain_session.DomainSDKOwner = OfflineOwner
    MessagesAPIBackend.complete = no_provider
    ClaudeCodeBackend.complete = no_provider
    StateImage._write_manifest = manifest
    StateImage._replace = image
    LazySQLiteStateRepository.apply = apply
    config = replace(default_config(), workspace_root_dir=Path(root))
    service = ProjectService(
        config, runtime_root=Path(runtime), owner_run_id=str(uuid4())
    )
    server = BridgeServer(config=config, project_service=service)
    await service.start()
    await service._bootstrap_task
    await server._ensure_application_state()
    packets = []

    async def emit(packet):
        packets.append(packet)

    await server.domains.handle(
        dict(
            type="activate_domain",
            protocol_version=2,
            request_id="start",
            domain_id=domain,
            expected_domain_revision="0",
        ),
        context=context(),
        emit=emit,
    )
    active = server.domains.snapshot(domain)
    await server.domains.handle(
        dict(
            type="domain_query",
            protocol_version=2,
            request_id="crash-run",
            domain_id=domain,
            agent_id="systems-architect" if domain == "core" else "backend-architect",
            task="Offline work",
            domain_session_id=active["domain_session_id"],
            execution_id=active["execution_id"],
        ),
        context=context(),
        emit=emit,
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
