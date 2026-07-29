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

# Catalog expansion (C1-C6) - representative ids checked by test_catalog_docs (C0.7).
CATALOG_ANALYZER_IDS: tuple[str, ...] = (
    "ruff",
    "mypy",
    "pyright",
    "basedpyright",
    "eslint",
    "biome",
    "oxlint",
    "osv-scanner",
    "trivy",
    "trufflehog",
    "semgrep",
    "ast-grep",
    "oasdiff",
    "squawk",
    "buf",
    "agentsec",
    "golangci-lint",
    "sqlfluff",
    "checkov",
)

# Every shipped catalog id — redaction parametrisation (C0.8 / C6).
_ALL_CATALOG_IDS: tuple[str, ...] = (
    "actionlint",
    "agentsec",
    "ast-grep",
    "basedpyright",
    "biome",
    "blinter",
    "brakeman",
    "buf",
    "checkmake",
    "checkov",
    "circleci",
    "clang-tidy",
    "clippy",
    "cppcheck",
    "detekt",
    "dotenv-linter",
    "ember-template-lint",
    "eslint",
    "flake8",
    "fortitude",
    "golangci-lint",
    "hadolint",
    "htmlhint",
    "infer",
    "languagetool",
    "luacheck",
    "markdownlint",
    "mypy",
    "oasdiff",
    "opengrep",
    "osv-scanner",
    "oxlint",
    "phpcs",
    "phpmd",
    "phpstan",
    "pmd",
    "presidio",
    "prisma-lint",
    "psscriptanalyzer",
    "pylint",
    "pyright",
    "regal",
    "rubocop",
    "ruff",
    "semgrep",
    "shellcheck",
    "shopify-theme-check",
    "smarty-lint",
    "sqlfluff",
    "squawk",
    "stylelint",
    "swiftlint",
    "tflint",
    "trivy",
    "trufflehog",
    "yamllint",
    "zizmor",
)

# All analyzer ids covered by redaction tests (full shipped catalog, C0.8 / C6).
REDACTION_ANALYZER_IDS: tuple[str, ...] = _ALL_CATALOG_IDS

# Planted secret for TruffleHog supply-chain tests — must never appear in outputs (D8).
PLANTED_AWS_SECRET = "AKIA_PLANTED_FIXTURE_DO_NOT_ROTATE_IN_TESTS"

# C1 language-gate tool ids and their planted paths.
C1_LANGUAGE_TOOLS: dict[str, tuple[str, int]] = {
    "ruff": ("src/fixture_app/handler.py", 13),
    "mypy": ("src/fixture_app/handler.py", 8),
    "pyright": ("src/fixture_app/handler.py", 8),
    "basedpyright": ("src/fixture_app/handler.py", 8),
    "eslint": ("src/index.js", 2),
}

C1_TYPE_CHECKERS: frozenset[str] = frozenset({"mypy", "pyright", "basedpyright"})

# C2 supply-chain planted targets.
C2_SUPPLY_CHAIN_TOOLS: dict[str, str] = {
    "osv-scanner": "requirements.txt",
    "trivy": "requirements.txt",
    "trufflehog": "config/planted-secret.env",
}

# C3 pattern scanner targets.
C3_PATTERN_TOOLS: dict[str, tuple[str, int]] = {
    "semgrep": ("src/fixture_app/eval_sink.py", 10),
    "ast-grep": ("src/fixture_app/eval_sink.py", 10),
}

# C4 contract tools and planted paths.
C4_CONTRACT_TOOLS: dict[str, str] = {
    "oasdiff": "openapi/v1.yaml",
    "squawk": "db/migrations/001_add_users.sql",
    "buf": "proto/user/v1/user.proto",
}

# C5 agent-security planted targets.
C5_AGENTSEC_TARGETS: dict[str, str] = {
    "mcp-exfil": ".mergecraft/mcp-servers/evil-server.yaml",
    "skill-injection": ".cursor/rules/exfil-skill.md",
}

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
