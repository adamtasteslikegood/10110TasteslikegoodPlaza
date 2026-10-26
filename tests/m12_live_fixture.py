"""Synthetic amendment proof for validator mutations; never provider evidence.

The retained historical run supplies a structurally rich template. Every changed
contract below is fabricated for offline testing, with deliberately dummy source
hashes. Nothing is written back to that historical record or acceptance artifacts.
"""

import json
from pathlib import Path


def synthetic_proof():
    from scripts.m12_live import INSTRUMENTATION, LIVE_SOURCES

    old = json.loads(
        (
            Path(__file__).parents[1] / "specs/evidence/m12-live-2026-10-21.json"
        ).read_text()
    )
    encoded = (
        json.dumps(old)
        .replace("engineering", "core")
        .replace("backend-architect", "systems-architect")
    )
    for key in ("initial", "isolation"):
        work = old[key]["workspace"]
        encoded = encoded.replace(
            work["worktree_path"],
            str(Path(work["worktree_path"]).parent / "core/execution"),
        )
        encoded = encoded.replace(work["branch"] + '"', work["branch"] + '-core"')
    record = json.loads(encoded)
    record["instrumentation"] = INSTRUMENTATION
    record["permission_mode"] = "dontAsk"
    hashes = {name: "a" * 64 for name in LIVE_SOURCES}
    record["binding"]["source_sha256"] = hashes
    for name in ("runtime_before", "runtime_after"):
        record["binding"][name]["tracked_sha256"].update(hashes)
    initial = record["initial"]
    stages = {s["stage"]: s for s in initial["stages"]}
    stages["chief_ready"]["payload"].pop("workspace_id")
    stages["npc_rendered"]["payload"]["agent_id"] = "fixture-extra-a"
    rendered = stages["domain_rendered"]["payload"]
    rendered["rendered_text"] = rendered["rendered_text"].replace(
        " · output ", " · systems-architect · output "
    )
    for stage_name in ("referral_rendered", "chief_ready", "npc_rendered"):
        request = stages[stage_name]["payload"]["request_id"]
        for collection in initial["wire"].values():
            for packet in collection:
                if packet.get("request_id") == request:
                    if stage_name == "npc_rendered":
                        packet["agent_id"] = "fixture-extra-a"
                    else:
                        packet["type"] = "project_setup"
    start_command = next(
        c for c in initial["wire"]["commands"] if c.get("type") == "activate_domain"
    )
    for name in ("initial", "restart", "isolation"):
        section = record[name]
        work = section["workspace"]
        work["domain_id"] = "core"
        section["sdk"]["permission_mode"] = "dontAsk"
        section["start"] = dict(
            request_id=(
                start_command["request_id"] if name == "initial" else "readback-start"
            ),
            project_id=work["project_id"],
            workspace_id=work["workspace_id"],
            domain_id="core",
            domain_session_id=(
                stages["domain_running"]["payload"]["domain_session_id"]
                if name == "initial"
                else name + "-generation"
            ),
            query_count=0,
        )
        section["context"] = dict(
            project_id=work["project_id"],
            workspace_id=work["workspace_id"],
            facts=dict(
                source_root=work["project_root"],
                agent_id="systems-architect",
                execution_kind="domain",
                domain_id="core",
                tools=["Read", "Edit", "Bash"],
                permission_mode="dontAsk",
                interaction="explicit_run",
                execution_capacity=1,
            ),
            sources=[
                dict(identity=identity, scope=scope, revision="b" * 64)
                for identity, scope in (
                    ("application-recap", "quoted-continuity"),
                    ("/fixture/bridge/context/GAME_CONTEXT.md", "shipped"),
                    ("/fixture/" + name + "/context/GAME_CONTEXT.md", "installation"),
                    ("/fixture/bridge/context/WORK_CONTEXT.md", "shipped"),
                    ("/fixture/" + name + "/context/WORK_CONTEXT.md", "installation"),
                    (work["project_root"] + "/PLAZA_AGENTS.md", "project"),
                    ("bridge-runtime", "runtime"),
                )
            ],
        )
    return record
