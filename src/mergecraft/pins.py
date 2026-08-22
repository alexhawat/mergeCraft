"""Canonical Action and install pins from example-workflow defaults."""

from __future__ import annotations

import os
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Final

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECKOUT_DEFAULTS_PATH: Final[Path] = (
    _REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"
)
# Sync rule: edit scripts/example_workflows/defaults.yaml, copy byte-identical to packaged path, then make pins-check.
_PACKAGED_DEFAULTS_PATH: Final[str] = "example_workflows/defaults.yaml"

# G1 option B — embedded fallback when neither checkout nor wheel data is present.
_FALLBACK_DEFAULTS: Final[dict[str, str]] = {
    "action_repo": "alexhawat/mergeCraft",
    "action_pin_minimal": "v0.1.0a1",
    "action_pin_hardened": "REPLACE_WITH_FULL_COMMIT_SHA",
    "ci_job_prefix": "Verify (",
    "base_branches": "[main]",
}


def _read_yaml_mapping(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"expected mapping in {path}"
        raise TypeError(msg)
    return {str(key): str(value) for key, value in raw.items()}


def _packaged_defaults() -> dict[str, str] | None:
    resource = files("mergecraft.data").joinpath(_PACKAGED_DEFAULTS_PATH)
    if not resource.is_file():
        return None
    raw = yaml.safe_load(resource.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return {str(key): str(value) for key, value in raw.items()}


@lru_cache(maxsize=1)
def load_example_defaults() -> dict[str, str]:
    """Load shared example-workflow placeholders and apply env overrides."""
    if _CHECKOUT_DEFAULTS_PATH.is_file():
        defaults = _read_yaml_mapping(_CHECKOUT_DEFAULTS_PATH)
    else:
        packaged = _packaged_defaults()
        defaults = packaged if packaged is not None else dict(_FALLBACK_DEFAULTS)
    env_map = {
        "action_repo": "MERGECRAFT_EXAMPLE_ACTION_REPO",
        "action_pin_minimal": "MERGECRAFT_EXAMPLE_ACTION_PIN_MINIMAL",
        "action_pin_hardened": "MERGECRAFT_EXAMPLE_ACTION_PIN_HARDENED",
        "ci_job_prefix": "MERGECRAFT_EXAMPLE_CI_JOB_PREFIX",
        "base_branches": "MERGECRAFT_EXAMPLE_BASE_BRANCHES",
    }
    for key, env_name in env_map.items():
        if env_name in os.environ:
            defaults[key] = os.environ[env_name]
    return defaults


def action_pin_minimal() -> str:
    """Return the canonical minimal Action pin (for example ``v0.1.0a1``)."""
    return load_example_defaults()["action_pin_minimal"].strip()
