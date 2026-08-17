"""Run manifest fingerprints and local telemetry defaults (CC2 / D11).

The manifest records reproducibility hashes (prompt, config, policy) plus the
model and CLI versions that produced a run. Telemetry defaults keep local
private-repo reviews from shipping spans to remote sinks unless the operator
opts in explicitly (D11).
"""

from __future__ import annotations

import hashlib
import os
import pathlib
from typing import TYPE_CHECKING, Any

from mergecraft import __version__
from mergecraft.cli.tracing_precedence import resolve_tracing_settings
from mergecraft.config.settings import _DEFAULT_CONFIG_REL, default_settings

if TYPE_CHECKING:
    from pathlib import Path

_REMOTE_SINKS = frozenset({"logfire", "otel"})


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_run_manifest(
    *,
    cwd: Path,
    model: str,
    agent_id: str,
    prompt_text: str,
    config_path: Path | None = None,
    policy_text: str | None = None,
) -> dict[str, Any]:
    """Return manifest metadata merged into evidence packets and run records."""
    resolved_config = config_path
    if resolved_config is None:
        candidate = pathlib.Path(cwd) / _DEFAULT_CONFIG_REL
        resolved_config = candidate if candidate.is_file() else None
    config_body = ""
    if resolved_config is not None and resolved_config.is_file():
        config_body = resolved_config.read_text(encoding="utf-8")
    policy = policy_text or default_settings().gates.gate_action
    prompt_hash = _sha256(prompt_text)
    config_hash = _sha256(config_body)
    policy_hash = _sha256(policy)
    return {
        "agent_id": agent_id,
        "model_version": model,
        "model_versions": {"requested": model, "executed": model},
        "cli_version": __version__,
        "cli_versions": {"mergecraft": __version__},
        "prompt_hash": prompt_hash,
        "config_hash": config_hash,
        "policy_hash": policy_hash,
        "hashes": {
            "prompt": prompt_hash,
            "config": config_hash,
            "policy": policy_hash,
        },
    }


def resolve_local_telemetry_defaults(
    *,
    cwd: Path | None = None,
    private_repo: bool = True,
) -> dict[str, Any]:
    """Return tracing defaults for a local CLI review (D11).

    Private/local runs ship nothing remotely by default. Remote sinks require
    explicit operator opt-in via env, YAML, or CLI flags.
    """
    del cwd  # reserved for future repo-aware policy
    if not private_repo:
        return resolve_tracing_settings(cli_args=[], env={**os.environ})
    explicit_remote = os.environ.get("MERGECRAFT_TRACING_TO", "").strip().lower() in _REMOTE_SINKS
    explicit_token = bool(os.environ.get("MERGECRAFT_LOGFIRE_TOKEN", "").strip())
    if explicit_remote or explicit_token:
        return resolve_tracing_settings(cli_args=[], env={**os.environ})
    return {"enabled": False, "tracing_to": None}


def apply_local_telemetry_defaults(*, private_repo: bool = True) -> dict[str, str | None]:
    """Apply D11 defaults to ``os.environ`` when remote telemetry is not opted in.

    Returns the previous values for keys touched so callers can restore them.
    """
    defaults = resolve_local_telemetry_defaults(private_repo=private_repo)
    if defaults.get("enabled"):
        return {}
    previous: dict[str, str | None] = {}
    for key in ("MERGECRAFT_TRACING", "MERGECRAFT_TRACING_TO", "MERGECRAFT_LOGFIRE_TOKEN"):
        if (
            key in os.environ
            and os.environ.get("MERGECRAFT_TRACING_TO", "").strip().lower() in _REMOTE_SINKS
        ):
            continue
        if key in os.environ and key == "MERGECRAFT_LOGFIRE_TOKEN" and os.environ[key].strip():
            continue
        if key in os.environ:
            previous[key] = os.environ[key]
            os.environ.pop(key, None)
    if "MERGECRAFT_TRACING" not in os.environ:
        previous.setdefault("MERGECRAFT_TRACING", os.environ.get("MERGECRAFT_TRACING"))
        os.environ["MERGECRAFT_TRACING"] = "false"
    return previous


__all__ = [
    "apply_local_telemetry_defaults",
    "build_run_manifest",
    "resolve_local_telemetry_defaults",
]
