"""Paths whose content governs how a PR is reviewed — analyzer, linter and mergeCraft config.

A PR that edits these can reduce the scrutiny applied to itself (#942), so blast-radius
classification keeps it out of the ``eligible`` auto-merge lane and the ``self-silencing``
analyzer inspects the edit. ``pyproject.toml`` is deliberately absent from the set the
classifier uses: it is already a dependency file (medium lane) and the analyzer reads its
``[tool.*]`` tables separately.

Module: mergecraft.classify.review_config
Depends: none (pure)

Exports:
    Constants:
        REVIEW_CONFIG_NAMES — Base file names of analyzer and linter config.
        RUN_STATE_FILE_NAMES — ``.mergecraft/`` files that are run state, not config.
    Functions:
        is_review_config_path — Whether a repo-relative path is review-governing config.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Final

REVIEW_CONFIG_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ruff.toml",
        ".ruff.toml",
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintrc.yaml",
        ".eslintrc.js",
        ".eslintrc.cjs",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "eslint.config.ts",
        ".golangci.yml",
        ".golangci.yaml",
        ".rubocop.yml",
        ".semgrepignore",
        ".semgrep.yml",
        "semgrep.yml",
        ".gitleaks.toml",
        ".gitleaksignore",
        ".trivyignore",
        ".bandit",
        "bandit.yaml",
        "bandit.yml",
        "setup.cfg",
        "tox.ini",
        ".flake8",
        ".pylintrc",
        "mypy.ini",
        "tsconfig.json",
        "biome.json",
        ".pre-commit-config.yaml",
    }
)

#: ``.mergecraft/`` entries the tool itself writes during a run; editing them is not a
#: configuration change.
RUN_STATE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {"learnings.md", "feedback.json", "memory.json", "analyzers.lock"}
)
_RUN_STATE_DIRS: Final[tuple[str, ...]] = (
    ".mergecraft/analyzer-scratch/",
    ".mergecraft/analyzer-runs/",
    ".mergecraft/analyzer-cache/",
)


def is_review_config_path(path: str) -> bool:
    """True when ``path`` is analyzer, linter or mergeCraft config (not run state)."""
    normalized = path.strip().lstrip("./") if path.startswith("./") else path.strip()
    posix = PurePosixPath(normalized)
    if normalized.startswith(".mergecraft/"):
        if normalized.startswith(_RUN_STATE_DIRS):
            return False
        return posix.name not in RUN_STATE_FILE_NAMES
    return posix.name in REVIEW_CONFIG_NAMES or posix.name.startswith(".eslintrc")


__all__ = ["REVIEW_CONFIG_NAMES", "RUN_STATE_FILE_NAMES", "is_review_config_path"]
