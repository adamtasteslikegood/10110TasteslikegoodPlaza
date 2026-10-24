"""Permission selection is strict and does not weaken domain guards."""

import json
from types import SimpleNamespace

import pytest
from bridge.config import default_config, load_config, ConfigError
from bridge.domain_sdk import domain_options


@pytest.mark.parametrize(
    "value,mode", [(False, "dontAsk"), (True, "bypassPermissions")]
)
def test_mode_config_env_and_sdk(tmp_path, value, mode):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS": value}))
    config = load_config(path, environ={})
    assert config.domain_permission_mode == mode
    assert config.effective_settings()["DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS"] is value
    override = load_config(
        path,
        environ={"PLAZA_DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS": json.dumps(not value)},
    )
    assert override.domain_permission_mode != mode
    hook = object()
    options = domain_options(config, SimpleNamespace(worktree_path=tmp_path), hook)
    assert options.permission_mode == mode
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )

    transport = SubprocessCLITransport(prompt="fixture", options=options)
    transport._cli_path = "/synthetic/claude"
    command = transport._build_command()
    assert command.count("--permission-mode") == 1
    assert command[command.index("--permission-mode") + 1] == mode
    assert "--dangerously-skip-permissions" not in command
    assert options.tools == options.allowed_tools == ["Read", "Edit", "Bash"]
    assert options.cwd == str(tmp_path)
    assert options.max_turns == config.domain_max_turns
    assert options.max_budget_usd == config.domain_max_budget_usd
    assert options.hooks["PreToolUse"][0].hooks == [hook]
    assert options.extra_args == {"print": None, "no-session-persistence": None}
    assert options.setting_sources == options.skills == options.plugins == []
    assert options.mcp_servers == options.agents == {}


@pytest.mark.parametrize("value", ["true", 1, 0, None, [], {}])
def test_invalid_permission_values(tmp_path, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS": value}))
    with pytest.raises(ConfigError):
        load_config(path, environ={})
    path.write_text("{}")
    with pytest.raises(ConfigError):
        load_config(
            path,
            environ={"PLAZA_DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS": json.dumps(value)},
        )


def test_default_permission_mode():
    assert default_config().domain_permission_mode == "dontAsk"
