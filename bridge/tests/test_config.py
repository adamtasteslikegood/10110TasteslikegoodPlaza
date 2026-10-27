"""Contract for the immutable, startup-only bridge settings snapshot."""

import dataclasses
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from bridge import config as config_module
from bridge.config import BridgeConfig, ConfigError, default_config, load_config

DEFAULTS = {
    "CONFIG_VERSION": 1,
    "HAIKU_MODEL": "claude-haiku-5-5",
    "SONNET_MODEL": "claude-sonnet-5-5",
    "OPUS_MODEL": "claude-opus-5-5",
    "FABLE_MODEL": "claude-fable-5-1",
    "ADVISOR_MODEL": "FABLE_MODEL",
    "CONVERSATION_BACKEND": "claude_code",
    "CONVERSATION_TIER": "haiku",
    "DOMAIN_TIER": "sonnet",
    "DOMAIN_STATE_BACKEND": "sqlite",
    "CONVERSATION_TIMEOUT_SECONDS": 60,
    "CONVERSATION_MAX_OUTPUT_TOKENS": 4096,
    "CONTEXT_MAX_MESSAGES": 40,
    "DOMAIN_MAX_TURNS": 20,
    "DOMAIN_DANGEROUSLY_SKIP_PERMISSIONS": False,
    "DOMAIN_MAX_BUDGET_USD": 1.0,
    "TRANSCRIPTS_ENABLED": True,
    "LOG_DIR": "../.local/bridge-logs",
    "LOG_LEVEL": "INFO",
    "TRANSCRIPT_MAX_RECORD_BYTES": 262144,
    "TRANSCRIPT_MAX_FILE_BYTES": 5242880,
    "LOG_MAX_TOTAL_BYTES": 104857600,
    "LOG_MAX_AGE_DAYS": 14,
    "WORKSPACE_ROOT_DIR": None,
    "INSTALL_CONTEXT_DIR": "../.local/plaza-context",
    "PROJECT_GUIDANCE_FILE": "PLAZA_AGENTS.md",
}
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config.json"
INTEGER_KEYS = [
    "CONVERSATION_MAX_OUTPUT_TOKENS",
    "CONTEXT_MAX_MESSAGES",
    "DOMAIN_MAX_TURNS",
    "TRANSCRIPT_MAX_RECORD_BYTES",
    "TRANSCRIPT_MAX_FILE_BYTES",
    "LOG_MAX_TOTAL_BYTES",
    "LOG_MAX_AGE_DAYS",
]
NUMBER_KEYS = ["CONVERSATION_TIMEOUT_SECONDS", "DOMAIN_MAX_BUDGET_USD"]
TEXT_KEYS = [
    "HAIKU_MODEL",
    "SONNET_MODEL",
    "OPUS_MODEL",
    "FABLE_MODEL",
    "ADVISOR_MODEL",
    "CONVERSATION_BACKEND",
    "CONVERSATION_TIER",
    "DOMAIN_TIER",
    "LOG_DIR",
    "LOG_LEVEL",
]


def write_config(tmp_path, values):
    selected = tmp_path / "config.json"
    selected.write_text(json.dumps(values), encoding="utf-8")
    return selected


def test_complete_defaults_and_committed_file_agree():
    assert json.loads(DEFAULT_PATH.read_text()) == DEFAULTS
    settings = default_config()
    assert isinstance(settings, BridgeConfig)
    expected = dict(
        DEFAULTS,
        LOG_DIR=str((DEFAULT_PATH.parent / DEFAULTS["LOG_DIR"]).resolve()),
        INSTALL_CONTEXT_DIR=str(
            (DEFAULT_PATH.parent / DEFAULTS["INSTALL_CONTEXT_DIR"]).resolve()
        ),
    )
    assert settings.effective_settings() == expected
    assert load_config(environ={}) == settings
    assert settings.source_path == DEFAULT_PATH
    for key, value in expected.items():
        assert getattr(settings, key.lower()) == (
            Path(value) if key in ("LOG_DIR", "INSTALL_CONTEXT_DIR") else value
        )


def test_partial_file_overlay_and_path_environment_precedence(tmp_path, monkeypatch):
    selected = write_config(
        tmp_path,
        {"DOMAIN_MAX_TURNS": 7, "HAIKU_MODEL": "file-model", "LOG_DIR": "logs"},
    )
    settings = load_config(selected, environ={})
    assert settings.domain_max_turns == 7
    assert settings.sonnet_model == DEFAULTS["SONNET_MODEL"]
    assert settings.log_dir == (tmp_path / "logs").resolve()
    env = {
        "BRIDGE_CONFIG_PATH": str(tmp_path / "missing"),
        "PLAZA_HAIKU_MODEL": "env-model",
    }
    assert load_config(selected, environ=env).haiku_model == "env-model"
    env["BRIDGE_CONFIG_PATH"] = str(selected)
    assert load_config(environ=env).source_path == selected
    # Exercise only the declared process overrides, independently of harness flags.
    for name in tuple(os.environ):
        if name.startswith("PLAZA_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("BRIDGE_CONFIG_PATH", str(selected))
    monkeypatch.setenv("PLAZA_HAIKU_MODEL", "process-model")
    assert load_config().haiku_model == "process-model"
    assert load_config(selected, environ={}).haiku_model == "file-model"


def test_relative_log_dir_is_independent_of_cwd(tmp_path, monkeypatch):
    selected = write_config(tmp_path, {"LOG_DIR": "logs"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_config(selected, environ={}).log_dir == tmp_path / "logs"
    assert load_config(environ={}).source_path == DEFAULT_PATH
    monkeypatch.chdir(tmp_path)
    assert load_config(Path("config.json"), environ={}).source_path == selected
    selected = write_config(tmp_path, {"LOG_DIR": str(tmp_path / "archive")})
    assert load_config(selected, environ={}).log_dir == tmp_path / "archive"


def test_snapshot_is_immutable_and_reload_is_explicit(tmp_path):
    selected = write_config(tmp_path, {"DOMAIN_MAX_TURNS": 3})
    env = {"PLAZA_HAIKU_MODEL": "first-model"}
    settings = load_config(selected, environ=env)
    selected.write_text('{"DOMAIN_MAX_TURNS": 9}')
    env["PLAZA_HAIKU_MODEL"] = "second-model"
    assert settings.domain_max_turns == 3
    assert settings.haiku_model == "first-model"
    assert load_config(selected, environ=env).domain_max_turns == 9
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.domain_max_turns = 4
    settings.effective_settings()["HAIKU_MODEL"] = "mutated"
    assert settings.haiku_model == "first-model"


def test_model_resolution_and_effective_settings_exclude_credentials(tmp_path):
    selected = write_config(
        tmp_path, {"HAIKU_MODEL": "custom-haiku", "SONNET_MODEL": "custom-sonnet"}
    )
    settings = load_config(
        selected, environ={"ANTHROPIC_API_KEY": "secret", "OTHER": "ignored"}
    )
    assert settings.model_for("haiku") == "custom-haiku"
    assert settings.model_for("sonnet") == "custom-sonnet"
    for invalid in ("unknown", "Haiku", "", None):
        with pytest.raises(ConfigError, match="tier"):
            settings.model_for(invalid)
    assert set(settings.effective_settings()) == set(DEFAULTS)
    assert "secret" not in json.dumps(settings.effective_settings())


def test_default_config_does_not_read_files_or_environment(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("implicit file read")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setenv("PLAZA_CONTEXT_MAX_MESSAGES", "3")
    assert default_config().context_max_messages == 40


def test_missing_default_falls_back_but_explicit_missing_fails(tmp_path, monkeypatch):
    selected = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "__file__", str(tmp_path / "config.py"))
    settings = load_config(environ={})
    assert settings.source_path == selected
    assert settings.context_max_messages == 40
    for path, env in [(selected, {}), (None, {"BRIDGE_CONFIG_PATH": str(selected)})]:
        with pytest.raises(ConfigError, match="config"):
            load_config(path, environ=env)


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        "true",
        "42",
        '"text"',
        "{",
        '{"LOG_LEVEL":"INFO","LOG_LEVEL":"DEBUG"}',
    ],
)
def test_rejects_non_object_malformed_and_duplicate_json(tmp_path, raw):
    selected = tmp_path / "config.json"
    selected.write_text(raw)
    with pytest.raises(ConfigError, match="config|LOG_LEVEL"):
        load_config(selected, environ={})


def test_unreadable_and_invalid_encoding_files_fail(tmp_path, monkeypatch):
    selected = write_config(tmp_path, {})
    selected.write_bytes(b"\xff")
    with pytest.raises(ConfigError, match="config"):
        load_config(selected, environ={})

    def unreadable(*args, **kwargs):
        raise PermissionError("not readable")

    monkeypatch.setattr(Path, "read_text", unreadable)
    for path in (selected, None):
        with pytest.raises(ConfigError, match="config"):
            load_config(path, environ={})


@pytest.mark.parametrize(
    "key", ["UNKNOWN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"]
)
def test_unknown_and_credential_keys_are_rejected(tmp_path, key):
    selected = write_config(tmp_path, {key: "credential-sentinel"})
    with pytest.raises(ConfigError, match=key) as error:
        load_config(selected, environ={})
    assert "credential-sentinel" not in str(error.value)
    selected = write_config(tmp_path, {})
    with pytest.raises(ConfigError, match=key):
        load_config(selected, environ={f"PLAZA_{key}": "credential-sentinel"})


@pytest.mark.parametrize("key", INTEGER_KEYS + NUMBER_KEYS)
@pytest.mark.parametrize(
    "value",
    [True, False, 0, -1, None, "12", [], {}, float("nan"), float("inf"), -float("inf")],
)
def test_numeric_settings_reject_invalid_file_values(tmp_path, key, value):
    # NaN/Infinity are invalid JSON syntax, rejected before setting validation.
    message = (
        "config file must contain valid JSON"
        if isinstance(value, float) and not math.isfinite(value)
        else key
    )
    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, {key: value}), environ={})


@pytest.mark.parametrize("key", INTEGER_KEYS)
def test_integer_settings_reject_fractional_values(tmp_path, key):
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {key: 2.5}), environ={})


@pytest.mark.parametrize(
    "key", INTEGER_KEYS + NUMBER_KEYS + ["CONFIG_VERSION", "TRANSCRIPTS_ENABLED"]
)
@pytest.mark.parametrize(
    "raw", ["", "not-json", "null", '"2"', "[]", "{}", "NaN", "Infinity", "-Infinity"]
)
def test_numeric_boolean_env_overrides_use_json_scalars(tmp_path, key, raw):
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {}), environ={f"PLAZA_{key}": raw})


@pytest.mark.parametrize(
    "key,value",
    [
        ("CONFIG_VERSION", 2),
        ("CONFIG_VERSION", True),
        ("CONFIG_VERSION", 1.5),
        ("CONFIG_VERSION", "1"),
        ("TRANSCRIPTS_ENABLED", 1),
        ("TRANSCRIPTS_ENABLED", "true"),
    ],
)
def test_version_and_boolean_types_are_strict(tmp_path, key, value):
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {key: value}), environ={})


@pytest.mark.parametrize("key", TEXT_KEYS)
@pytest.mark.parametrize("value", ["", "  ", None, 42, True, [], {}])
def test_text_settings_require_nonempty_strings(tmp_path, key, value):
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {key: value}), environ={})


@pytest.mark.parametrize(
    "key,value",
    [
        ("CONVERSATION_TIER", "unknown"),
        ("DOMAIN_TIER", "Haiku"),
        ("LOG_LEVEL", "info"),
        ("LOG_LEVEL", "CRITICAL"),
        ("CONTEXT_MAX_MESSAGES", 1),
        ("CONTEXT_MAX_MESSAGES", 3),
        ("TRANSCRIPT_MAX_RECORD_BYTES", 4095),
        ("TRANSCRIPT_MAX_FILE_BYTES", 262143),
        ("LOG_MAX_TOTAL_BYTES", 5242879),
    ],
)
def test_rejects_adjacent_bounds_and_unsupported_choices(tmp_path, key, value):
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {key: value}), environ={})


@pytest.mark.parametrize("level", ["INFO", "DEBUG", "WARNING", "ERROR"])
@pytest.mark.parametrize("tier", ["haiku", "sonnet", "opus", "fable"])
def test_accepts_supported_choices_and_minimum_limits(tmp_path, level, tier):
    values = {key: 1 for key in INTEGER_KEYS + NUMBER_KEYS}
    values.update(
        CONTEXT_MAX_MESSAGES=2,
        TRANSCRIPT_MAX_RECORD_BYTES=4096,
        TRANSCRIPT_MAX_FILE_BYTES=4096,
        LOG_MAX_TOTAL_BYTES=4096,
        LOG_LEVEL=level,
        CONVERSATION_TIER=tier,
        DOMAIN_TIER=tier,
    )
    settings = load_config(write_config(tmp_path, values), environ={})
    assert settings.context_max_messages == 2
    assert (
        settings.transcript_max_record_bytes
        == settings.transcript_max_file_bytes
        == settings.log_max_total_bytes
        == 4096
    )
    assert settings.log_level == level
    assert settings.conversation_tier == settings.domain_tier == tier


def test_valid_environment_overrides_are_parsed_by_setting_type(tmp_path):
    env = {
        f"PLAZA_{key}": value if isinstance(value, str) else json.dumps(value)
        for key, value in DEFAULTS.items()
        if key != "WORKSPACE_ROOT_DIR"
    }
    env.update(
        PLAZA_TRANSCRIPTS_ENABLED="false",
        PLAZA_DOMAIN_MAX_BUDGET_USD="0.25",
        PLAZA_CONVERSATION_TIMEOUT_SECONDS="0.5",
        PLAZA_HAIKU_MODEL="raw-model",
        PLAZA_CONTEXT_MAX_MESSAGES="42",
    )
    settings = load_config(write_config(tmp_path, {}), environ=env)
    assert settings.transcripts_enabled is False
    assert settings.domain_max_budget_usd == 0.25
    assert settings.conversation_timeout_seconds == 0.5
    assert settings.haiku_model == "raw-model"
    assert settings.context_max_messages == 42


def test_workspace_env_is_raw_and_config_relative(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    selected = write_config(settings_dir, {"WORKSPACE_ROOT_DIR": "../repo"})
    monkeypatch.chdir(tmp_path.parent)
    assert load_config(selected, environ={}).workspace_root_dir == repo.resolve()
    assert (
        load_config(
            selected, environ={"PLAZA_WORKSPACE_ROOT_DIR": "../repo"}
        ).workspace_root_dir
        == repo.resolve()
    )
    assert default_config().workspace_root_dir is None
    assert default_config().effective_settings()["WORKSPACE_ROOT_DIR"] is None
    literal = settings_dir / "null"
    literal.mkdir()
    settings = load_config(selected, environ={"PLAZA_WORKSPACE_ROOT_DIR": "null"})
    assert settings.workspace_root_dir == literal
    assert settings.effective_settings()["WORKSPACE_ROOT_DIR"] == str(literal)


@pytest.mark.parametrize(
    "value", ["", "  ", True, False, 1, [], {}, "missing", "bad\u0000path"]
)
def test_invalid_workspace_configuration_fails(tmp_path, value):
    with pytest.raises(ConfigError, match="WORKSPACE_ROOT_DIR"):
        load_config(write_config(tmp_path, {"WORKSPACE_ROOT_DIR": value}), environ={})


def test_workspace_file_rejected_and_symlink_canonicalized(tmp_path):
    selected = write_config(tmp_path, {"WORKSPACE_ROOT_DIR": "config.json"})
    with pytest.raises(ConfigError, match="WORKSPACE_ROOT_DIR"):
        load_config(selected, environ={})
    (tmp_path / "repo").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "repo", target_is_directory=True)
    assert (
        load_config(
            selected, environ={"PLAZA_WORKSPACE_ROOT_DIR": "alias"}
        ).workspace_root_dir
        == tmp_path / "repo"
    )


@pytest.mark.parametrize(
    "key",
    [
        "LOG_DIR",
        "HAIKU_MODEL",
        "SONNET_MODEL",
        "OPUS_MODEL",
        "FABLE_MODEL",
        "ADVISOR_MODEL",
    ],
)
def test_empty_text_overrides_fail(tmp_path, key):
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {}), environ={f"PLAZA_{key}": ""})


def test_empty_explicit_environment_path_fails():
    with pytest.raises(ConfigError, match="BRIDGE_CONFIG_PATH"):
        load_config(environ={"BRIDGE_CONFIG_PATH": ""})


@pytest.mark.parametrize(
    "key,accepted,rejected",
    [
        ("TRANSCRIPT_MAX_RECORD_BYTES", 5242880, 5242881),
        ("TRANSCRIPT_MAX_FILE_BYTES", 104857600, 104857601),
    ],
)
def test_byte_ordering_accepts_equal_upper_boundary_and_rejects_next_byte(
    tmp_path, key, accepted, rejected
):
    settings = load_config(write_config(tmp_path, {key: accepted}), environ={})
    assert settings.effective_settings()[key] == accepted
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, {key: rejected}), environ={})


def test_import_does_not_read_files_or_environment():
    script = """
import os
from pathlib import Path
import dataclasses, collections.abc, json, math
def forbidden(*args, **kwargs):
    raise AssertionError("implicit configuration access")
class ForbiddenEnvironment(dict):
    __getitem__ = get = items = __contains__ = forbidden
Path.read_text = Path.open = forbidden
os.environ = ForbiddenEnvironment()
import bridge.config
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", [2, True, 1.0, "1", None, [], {}])
def test_environment_cannot_mask_unsupported_file_version(tmp_path, version):
    selected = write_config(tmp_path, {"CONFIG_VERSION": version})
    with pytest.raises(ConfigError, match="CONFIG_VERSION"):
        load_config(selected, environ={"PLAZA_CONFIG_VERSION": "1"})


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_environment_cannot_mask_nonstandard_json_constants(tmp_path, constant):
    selected = tmp_path / "config.json"
    selected.write_text('{"DOMAIN_MAX_BUDGET_USD":' + constant + "}")
    with pytest.raises(ConfigError, match="config"):
        load_config(selected, environ={"PLAZA_DOMAIN_MAX_BUDGET_USD": "1"})


def test_supported_file_version_preserves_environment_validation_and_precedence(
    tmp_path,
):
    selected = write_config(tmp_path, {"CONFIG_VERSION": 1, "DOMAIN_MAX_TURNS": 7})
    settings = load_config(
        selected, environ={"PLAZA_CONFIG_VERSION": "1", "PLAZA_DOMAIN_MAX_TURNS": "9"}
    )
    assert settings.config_version == 1
    assert settings.domain_max_turns == 9
    with pytest.raises(ConfigError, match="CONFIG_VERSION"):
        load_config(selected, environ={"PLAZA_CONFIG_VERSION": "2"})


def test_ordinary_file_value_validation_follows_environment_overlay(tmp_path):
    selected = write_config(tmp_path, {"DOMAIN_MAX_TURNS": 0})
    assert (
        load_config(selected, environ={"PLAZA_DOMAIN_MAX_TURNS": "9"}).domain_max_turns
        == 9
    )


@pytest.mark.parametrize("tier", ["haiku", "sonnet", "opus", "fable"])
def test_all_model_slots_resolve_file_and_environment_overrides(tmp_path, tier):
    key = f"{tier.upper()}_MODEL"
    selected = write_config(tmp_path, {key: "file-model"})
    assert load_config(selected, environ={}).model_for(tier) == "file-model"
    settings = load_config(selected, environ={f"PLAZA_{key}": "env-model"})
    assert settings.model_for(tier) == "env-model"
    assert settings.effective_settings()[key] == "env-model"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(settings, key.lower(), "mutated")


@pytest.mark.parametrize(
    "reference", ["HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL", "FABLE_MODEL"]
)
def test_advisor_reference_accepts_each_model_slot_and_environment_precedence(
    tmp_path, reference
):
    selected = write_config(tmp_path, {"ADVISOR_MODEL": reference})
    assert load_config(selected, environ={}).advisor_model == reference
    settings = load_config(selected, environ={"PLAZA_ADVISOR_MODEL": "OPUS_MODEL"})
    assert settings.advisor_model == "OPUS_MODEL"
    assert settings.effective_settings()["ADVISOR_MODEL"] == "OPUS_MODEL"


@pytest.mark.parametrize(
    "reference",
    ["ADVISOR_MODEL", "UNKNOWN_MODEL", "fable", "fable_model", "claude-fable-5-1"],
)
def test_advisor_reference_rejects_self_unknown_and_provider_ids(tmp_path, reference):
    selected = write_config(tmp_path, {"ADVISOR_MODEL": reference})
    with pytest.raises(ConfigError, match="ADVISOR_MODEL"):
        load_config(selected, environ={})
    selected = write_config(tmp_path, {})
    with pytest.raises(ConfigError, match="ADVISOR_MODEL"):
        load_config(selected, environ={"PLAZA_ADVISOR_MODEL": reference})


HIGHER_ADVISORS = [
    ("haiku", "sonnet"),
    ("haiku", "opus"),
    ("haiku", "fable"),
    ("sonnet", "opus"),
    ("sonnet", "fable"),
    ("opus", "fable"),
]


@pytest.mark.parametrize("caller,advisor", HIGHER_ADVISORS)
def test_advisor_for_resolves_strictly_higher_tiers(tmp_path, caller, advisor):
    reference = f"{advisor.upper()}_MODEL"
    selected = write_config(
        tmp_path, {"ADVISOR_MODEL": reference, reference: "custom-advisor"}
    )
    settings = load_config(selected, environ={})
    assert settings.advisor_for(caller) == "custom-advisor"
    settings = load_config(selected, environ={f"PLAZA_{reference}": "env-advisor"})
    assert settings.advisor_for(caller) == "env-advisor"


@pytest.mark.parametrize(
    "caller,advisor",
    [
        ("haiku", "haiku"),
        ("sonnet", "haiku"),
        ("sonnet", "sonnet"),
        ("opus", "haiku"),
        ("opus", "sonnet"),
        ("opus", "opus"),
        ("fable", "haiku"),
        ("fable", "sonnet"),
        ("fable", "opus"),
        ("fable", "fable"),
    ],
)
def test_advisor_for_rejects_same_or_lower_tier_only_when_called(
    tmp_path, caller, advisor
):
    selected = write_config(
        tmp_path,
        {
            "ADVISOR_MODEL": f"{advisor.upper()}_MODEL",
            "CONVERSATION_TIER": caller,
            "DOMAIN_TIER": caller,
        },
    )
    settings = load_config(selected, environ={})
    assert settings.conversation_tier == settings.domain_tier == caller
    with pytest.raises(ConfigError, match="higher tier"):
        settings.advisor_for(caller)


@pytest.mark.parametrize("caller,advisor", HIGHER_ADVISORS)
def test_advisor_for_rejects_identical_provider_id_across_distinct_slots(
    tmp_path, caller, advisor
):
    selected = write_config(
        tmp_path,
        {
            "ADVISOR_MODEL": f"{advisor.upper()}_MODEL",
            f"{caller.upper()}_MODEL": "same-provider-id",
            f"{advisor.upper()}_MODEL": "same-provider-id",
        },
    )
    with pytest.raises(ConfigError, match="different provider ID"):
        load_config(selected, environ={}).advisor_for(caller)


def test_advisor_capability_order_ignores_numeric_model_version(tmp_path):
    selected = write_config(
        tmp_path,
        {
            "ADVISOR_MODEL": "SONNET_MODEL",
            "HAIKU_MODEL": "claude-haiku-99-0",
            "SONNET_MODEL": "claude-sonnet-1-0",
        },
    )
    assert load_config(selected, environ={}).advisor_for("haiku") == "claude-sonnet-1-0"


@pytest.mark.parametrize("caller", ["unknown", "Haiku", "", None])
def test_advisor_for_rejects_unknown_caller_tier(caller):
    with pytest.raises(ConfigError, match="tier"):
        default_config().advisor_for(caller)


def test_domain_state_backend_default_and_precedence(tmp_path):
    assert default_config().domain_state_backend == "sqlite"
    selected = write_config(tmp_path, {"DOMAIN_STATE_BACKEND": "memory"})
    assert load_config(selected, environ={}).domain_state_backend == "memory"
    settings = load_config(selected, environ={"PLAZA_DOMAIN_STATE_BACKEND": "sqlite"})
    assert settings.domain_state_backend == "sqlite"
    assert settings.effective_settings()["DOMAIN_STATE_BACKEND"] == "sqlite"


@pytest.mark.parametrize("value", ["", "SQLite", "jsonl", None, True, 1, [], {}])
def test_domain_state_backend_rejects_unknown_and_wrong_types(tmp_path, value):
    with pytest.raises(ConfigError, match="DOMAIN_STATE_BACKEND"):
        load_config(write_config(tmp_path, {"DOMAIN_STATE_BACKEND": value}), environ={})
