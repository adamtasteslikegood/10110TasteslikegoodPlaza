"""Validated bridge settings, loaded explicitly once by the process entry point.

Precedence: built-ins, selected JSON file, then PLAZA_<schema key> overrides.
Numeric and boolean overrides use JSON scalar syntax; text overrides are raw.
Importing this module performs no configuration or credential reads.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
import json
import math
import os
from pathlib import Path


class ConfigError(ValueError):
    """A configuration source or setting cannot be used safely."""


_DEFAULTS: dict[str, object] = {
    "CONFIG_VERSION": 1,
    "HAIKU_MODEL": "claude-haiku-5-5",
    "SONNET_MODEL": "claude-sonnet-5-5",
    "OPUS_MODEL": "claude-opus-5-5",
    "FABLE_MODEL": "claude-fable-5-1",
    "ADVISOR_MODEL": "FABLE_MODEL",
    "CONVERSATION_BACKEND": "claude_code",
    "CONVERSATION_TIER": "haiku",
    "DOMAIN_TIER": "sonnet",
    "CONVERSATION_TIMEOUT_SECONDS": 60,
    "CONVERSATION_MAX_OUTPUT_TOKENS": 4096,
    "CONTEXT_MAX_MESSAGES": 40,
    "DOMAIN_MAX_TURNS": 20,
    "DOMAIN_MAX_BUDGET_USD": 1.0,
    "TRANSCRIPTS_ENABLED": True,
    "LOG_DIR": "../.local/bridge-logs",
    "LOG_LEVEL": "INFO",
    "TRANSCRIPT_MAX_RECORD_BYTES": 262144,
    "TRANSCRIPT_MAX_FILE_BYTES": 5242880,
    "LOG_MAX_TOTAL_BYTES": 104857600,
    "LOG_MAX_AGE_DAYS": 14,
    "WORKSPACE_ROOT_DIR": None,
}
_TEXT_KEYS = frozenset(
    {
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
    }
)
_INTEGER_KEYS = frozenset(
    {
        "CONVERSATION_MAX_OUTPUT_TOKENS",
        "CONTEXT_MAX_MESSAGES",
        "DOMAIN_MAX_TURNS",
        "TRANSCRIPT_MAX_RECORD_BYTES",
        "TRANSCRIPT_MAX_FILE_BYTES",
        "LOG_MAX_TOTAL_BYTES",
        "LOG_MAX_AGE_DAYS",
    }
)
_NUMBER_KEYS = frozenset({"CONVERSATION_TIMEOUT_SECONDS", "DOMAIN_MAX_BUDGET_USD"})
_TIERS = ("haiku", "sonnet", "opus", "fable")
_MODEL_REFERENCES = tuple(f"{tier.upper()}_MODEL" for tier in _TIERS)


@dataclass(frozen=True)
class BridgeConfig:
    """A settings snapshot; reload explicitly by constructing a new snapshot."""

    config_version: int
    haiku_model: str
    sonnet_model: str
    opus_model: str
    fable_model: str
    advisor_model: str
    conversation_backend: str
    conversation_tier: str
    domain_tier: str
    conversation_timeout_seconds: int | float
    conversation_max_output_tokens: int
    context_max_messages: int
    domain_max_turns: int
    domain_max_budget_usd: int | float
    transcripts_enabled: bool
    log_dir: Path
    log_level: str
    transcript_max_record_bytes: int
    transcript_max_file_bytes: int
    log_max_total_bytes: int
    log_max_age_days: int
    source_path: Path
    workspace_root_dir: Path | None = None

    def model_for(self, tier: str) -> str:
        """Resolve an approved tier without model fallback or upgrades."""
        if tier not in _TIERS:
            raise ConfigError("model tier must be haiku, sonnet, opus or fable")
        return getattr(self, f"{tier}_model")

    def advisor_for(self, caller_tier: str) -> str:
        """Resolve future advice only to a distinct, strictly higher-tier model."""
        caller_model = self.model_for(caller_tier)
        advisor_tier = self.advisor_model.removesuffix("_MODEL").lower()
        advisor_model = self.model_for(advisor_tier)
        if _TIERS.index(advisor_tier) <= _TIERS.index(caller_tier):
            raise ConfigError("ADVISOR_MODEL must reference a strictly higher tier")
        if advisor_model == caller_model:
            raise ConfigError("ADVISOR_MODEL must resolve to a different provider ID")
        return advisor_model

    def effective_settings(self) -> dict[str, object]:
        """Return only schema values, safe for an effective-settings manifest."""
        return {
            field.name.upper(): (
                str(getattr(self, field.name))
                if isinstance(getattr(self, field.name), Path)
                else getattr(self, field.name)
            )
            for field in fields(self)
            if field.name != "source_path"
        }


def _default_path() -> Path:
    return Path(__file__).resolve().with_name("config.json")


def _build(values: Mapping[str, object], source_path: Path) -> BridgeConfig:
    for key in _TEXT_KEYS:
        value = values[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{key} must be a nonempty string")
    for key in _INTEGER_KEYS:
        if type(values[key]) is not int or values[key] <= 0:
            raise ConfigError(f"{key} must be a positive integer")
    for key in _NUMBER_KEYS:
        value = values[key]
        if (
            type(value) not in (int, float)
            or (type(value) is float and not math.isfinite(value))
            or value <= 0
        ):
            raise ConfigError(f"{key} must be a positive finite number")
    if type(values["CONFIG_VERSION"]) is not int or values["CONFIG_VERSION"] != 1:
        raise ConfigError("CONFIG_VERSION must be the supported integer version 1")
    if type(values["TRANSCRIPTS_ENABLED"]) is not bool:
        raise ConfigError("TRANSCRIPTS_ENABLED must be a boolean")
    if values["CONVERSATION_BACKEND"] not in ("claude_code", "messages_api"):
        raise ConfigError("CONVERSATION_BACKEND must be claude_code or messages_api")
    for key in ("CONVERSATION_TIER", "DOMAIN_TIER"):
        if values[key] not in _TIERS:
            raise ConfigError(f"{key} must be haiku, sonnet, opus or fable")
    if values["ADVISOR_MODEL"] not in _MODEL_REFERENCES:
        raise ConfigError(
            "ADVISOR_MODEL must reference HAIKU_MODEL, SONNET_MODEL, OPUS_MODEL or FABLE_MODEL"
        )
    if values["LOG_LEVEL"] not in ("INFO", "DEBUG", "WARNING", "ERROR"):
        raise ConfigError("LOG_LEVEL must be INFO, DEBUG, WARNING or ERROR")
    if values["CONTEXT_MAX_MESSAGES"] < 2 or values["CONTEXT_MAX_MESSAGES"] % 2:
        raise ConfigError("CONTEXT_MAX_MESSAGES must be even and at least 2")
    if values["TRANSCRIPT_MAX_RECORD_BYTES"] < 4096:
        raise ConfigError("TRANSCRIPT_MAX_RECORD_BYTES must be at least 4096")
    if values["TRANSCRIPT_MAX_RECORD_BYTES"] > values["TRANSCRIPT_MAX_FILE_BYTES"]:
        raise ConfigError(
            "TRANSCRIPT_MAX_RECORD_BYTES must not exceed TRANSCRIPT_MAX_FILE_BYTES"
        )
    if values["TRANSCRIPT_MAX_FILE_BYTES"] > values["LOG_MAX_TOTAL_BYTES"]:
        raise ConfigError(
            "TRANSCRIPT_MAX_FILE_BYTES must not exceed LOG_MAX_TOTAL_BYTES"
        )
    attributes = {key.lower(): value for key, value in values.items()}
    workspace = values["WORKSPACE_ROOT_DIR"]
    if workspace is not None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise ConfigError("WORKSPACE_ROOT_DIR must be null or a nonempty path")
        try:
            workspace_path = Path(workspace)
            if not workspace_path.is_absolute():
                workspace_path = source_path.parent / workspace_path
            workspace_path = workspace_path.resolve(strict=True)
            if not workspace_path.is_dir():
                raise ValueError("not a directory")
            attributes["workspace_root_dir"] = workspace_path
        except (OSError, ValueError, RuntimeError):
            raise ConfigError(
                "WORKSPACE_ROOT_DIR must identify an existing directory"
            ) from None
    try:
        log_dir = Path(values["LOG_DIR"])
        if not log_dir.is_absolute():
            log_dir = source_path.parent / log_dir
        attributes["log_dir"] = log_dir.resolve()
    except (OSError, ValueError, RuntimeError):
        raise ConfigError("LOG_DIR must identify a valid filesystem path") from None
    return BridgeConfig(**attributes, source_path=source_path)


def default_config() -> BridgeConfig:
    """Validate built-ins without reading a file or environment overrides."""
    return _build(_DEFAULTS, _default_path())


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"config contains duplicate key {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ConfigError(
        "config file must contain valid JSON: nonstandard numeric constant"
    )


def load_config(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> BridgeConfig:
    """Read and validate a complete snapshot; explicit missing sources fail.

    A missing default bridge/config.json uses built-ins. An explicit argument
    takes precedence over BRIDGE_CONFIG_PATH; all PLAZA_ names must be known.
    Unprefixed environment variables (including credentials) are left alone.
    """
    environment = os.environ if environ is None else environ
    explicit = path is not None or "BRIDGE_CONFIG_PATH" in environment
    selected = path if path is not None else environment.get("BRIDGE_CONFIG_PATH")
    if selected is not None and (not str(selected).strip()):
        raise ConfigError("BRIDGE_CONFIG_PATH must be a nonempty config path")
    try:
        source_path = Path(selected).resolve() if explicit else _default_path()
    except (OSError, ValueError, RuntimeError):
        raise ConfigError("config path must identify a valid filesystem path") from None
    values = dict(_DEFAULTS)
    try:
        document = source_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"config file does not exist: {source_path}") from None
    except (OSError, UnicodeError, ValueError):
        raise ConfigError(f"config file cannot be read: {source_path}") from None
    else:
        try:
            overlay = json.loads(
                document,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as error:
            if isinstance(error, ConfigError):
                raise
            raise ConfigError("config file must contain valid JSON") from None
        if not isinstance(overlay, dict):
            raise ConfigError("config file must contain a JSON object")
        for key in overlay:
            if key not in _DEFAULTS:
                raise ConfigError(f"unknown config setting {key}")
        if "CONFIG_VERSION" in overlay and (
            type(overlay["CONFIG_VERSION"]) is not int or overlay["CONFIG_VERSION"] != 1
        ):
            raise ConfigError("CONFIG_VERSION must be the supported integer version 1")
        values.update(overlay)
    for name, raw in environment.items():
        if not name.startswith("PLAZA_"):
            continue
        key = name.removeprefix("PLAZA_")
        if key not in _DEFAULTS:
            raise ConfigError(f"unknown config override {name}")
        if key in _TEXT_KEYS or key == "WORKSPACE_ROOT_DIR":
            values[key] = raw
        else:
            try:
                values[key] = json.loads(raw)
            except (ValueError, TypeError):
                raise ConfigError(
                    f"{key} override must use JSON scalar syntax"
                ) from None
    return _build(values, source_path)
