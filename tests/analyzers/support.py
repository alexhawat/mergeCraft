"""Shared constants and lazy imports for analyzer platform tests."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

_ANALYZERS_DIR = Path(__file__).resolve().parent

FIXTURE_REPO = _ANALYZERS_DIR / "fixtures" / "repo"
FIXTURES_DIR = _ANALYZERS_DIR / "fixtures"
MANIFEST_FIXTURES = FIXTURES_DIR / "manifests"

# W0.8 canary — must never escape any output path (D8).
CANARY_SECRET = "sk-canary-w0-8-do-not-leak-7f3a9b2c1d4e5f6a"

# W0.2 measured inline cap (D14).
INLINE_BUDGET = 8

# W6 adapter ids — redaction parametrisation is structurally valid before W6 (W1.12).
W6_ANALYZER_IDS: tuple[str, ...] = ("actionlint", "zizmor", "shellcheck", "hadolint")

# W0.4 probe run 30368443226: same-repo ``pull_request`` (fork=false).
SAME_REPO_PULL_REQUEST_EVENT: dict[str, Any] = {
    "action": "opened",
    "number": 1,
    "pull_request": {
        "head": {
            "ref": "wave/analyzer-platform",
            "sha": "abc123def456",
            "repo": {"full_name": "alexhawat/mergeCraft", "fork": False},
        },
        "base": {
            "ref": "pre-0.0.1",
            "sha": "b8e83a82e97ed537706d9a712e59af9ef031588f",
            "repo": {"full_name": "alexhawat/mergeCraft", "fork": False},
        },
        "html_url": "https://github.com/alexhawat/mergeCraft/pull/1",
    },
    "repository": {
        "full_name": "alexhawat/mergeCraft",
        "fork": False,
        "owner": {"login": "alexhawat"},
    },
}

# Fork PR event shape for untrusted-tier tests (real fork probe deferred to Verify).
FORK_PULL_REQUEST_EVENT: dict[str, Any] = {
    "action": "opened",
    "number": 42,
    "pull_request": {
        "head": {
            "ref": "feature",
            "sha": "forksha123",
            "repo": {
                "full_name": "contributor/mergeCraft",
                "fork": True,
                "owner": {"login": "contributor"},
            },
        },
        "base": {
            "ref": "pre-0.0.1",
            "sha": "b8e83a82e97ed537706d9a712e59af9ef031588f",
            "repo": {"full_name": "alexhawat/mergeCraft", "fork": False},
        },
    },
    "repository": {
        "full_name": "alexhawat/mergeCraft",
        "fork": False,
        "owner": {"login": "alexhawat"},
    },
}


def import_module(dotted: str) -> Any:
    """Lazy import so collection succeeds before W2 lands ``src/mergecraft/analyzers/``."""
    return importlib.import_module(dotted)


def load_json_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
