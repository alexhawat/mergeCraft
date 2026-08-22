"""Canonical Action and install pins from ``scripts/example_workflows/defaults.yaml``."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Final

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_PATH: Final[Path] = _REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"


@lru_cache(maxsize=1)
def load_example_defaults() -> dict[str, str]:
    """Load shared example-workflow placeholders and apply env overrides."""
    raw = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"expected mapping in {DEFAULTS_PATH}"
        raise TypeError(msg)
    defaults: dict[str, str] = {str(key): str(value) for key, value in raw.items()}
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
