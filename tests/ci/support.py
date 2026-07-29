"""Shared constants and helpers for CI intelligence tests (K0)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

_CI_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = _CI_DIR / "fixtures"

# K8 canary — must never escape any CI output path (excerpt, fingerprint, cache key).
CANARY_SECRET = "sk-canary-k8-ci-log-do-not-leak-9e4f2a1b0c3d5e7f"

# Normalized failure shape from K1.4 / K0.2.
NORMALIZED_FIELDS: tuple[str, ...] = (
    "job",
    "step",
    "command",
    "exit_code",
    "log_excerpt",
    "artifacts",
    "retry_state",
    "failure_fingerprint",
)

# Matches current ``get_check_suite_logs`` cap (K2.4 default until configured).
DEFAULT_TRUNCATION_CAP = 3

# D14 inline budget inherited from analyzer platform tests.
INLINE_BUDGET = 8

CI_SECTION_HEADING = "### 🚨 CI failures"

STUB_PROVIDER_IDS: tuple[str, ...] = ("circleci", "gitlab", "azure")


def import_module(dotted: str) -> Any:
    """Lazy import so collection succeeds before K1 creates ``src/mergecraft/ci/``."""
    return importlib.import_module(dotted)


def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name
    if not path.suffix:
        path = path.with_suffix(".json")
    return json.loads(path.read_text(encoding="utf-8"))
