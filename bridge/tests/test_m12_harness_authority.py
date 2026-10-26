"""The integration driver preserves explicit fences and unmatched wire replies."""

import json

import pytest

from bridge.tests.m12_harness import Socket
from scripts.m12_live import Plain


@pytest.fixture(params=[Socket, Plain], ids=["test-driver", "live-driver"])
def driver(request):
    return request.param


class Wire:
    def __init__(self, packets=()):
        self.sent = []
        self.packets = list(packets)

    async def send(self, data):
        packet = json.loads(data)
        self.sent.append(packet)
        if packet["type"] == "domain_status":
            self.packets.append(
                dict(
                    type="domain_state",
                    request_id=packet["request_id"],
                    domain_revision="7",
                    execution_id="new-execution",
                )
            )

    async def recv(self):
        return json.dumps(self.packets.pop(0))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,authority",
    [
        ("activate_domain", {"expected_domain_revision": "stale"}),
        ("end_domain_session", {"expected_domain_revision": None}),
        ("domain_query", {"execution_id": "stale-execution"}),
        ("deactivate_domain", {"execution_id": None}),
    ],
)
async def test_explicit_authority_does_not_issue_preflight(kind, authority, driver):
    wire = Wire()
    socket = driver(wire)
    command = await socket.send(kind, "explicit", "application", **authority)
    assert wire.sent == [command]
    assert all(command[key] == value for key, value in authority.items())


@pytest.mark.asyncio
async def test_authority_preflight_keeps_prior_terminal_retrievable(driver):
    terminal = dict(type="domain_result", request_id="prior", output_id="1")
    wire = Wire([terminal])
    socket = driver(wire)
    command = await socket.send("deactivate_domain", "stop", "application")
    assert command["execution_id"] == "new-execution"
    assert (await socket.reply("prior", type="domain_result")) == terminal
    assert [p["type"] for p in wire.sent] == ["domain_status", "deactivate_domain"]
