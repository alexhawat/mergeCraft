"""Characterisation suite for G4.1 — `analyzers/registry.py` (D26 / D22).

PR G4 (`.ignorelocal/waves/issues-showcase-readiness-wave-plan.md`, "PR G4")
extracts `_exclusive_group_winner`'s tie-break rules into named predicates
and `detect_enabled`'s per-detector evaluation into a helper — both in the
same file, same wave. This is a pure refactor: per G4.1's own acceptance
line, this test must be **green today**, against unmodified code, and
**stay green** after the extraction — the inverse of this repo's usual
RED-first convention.

`_exclusive_group_winner`'s D26 complexity is the explicit-override /
preference-ladder / alphabetical-tie-break chain; `detect_enabled`'s D22 is
the detect-match / settings-override / exclusive-group-collapse pipeline
that calls it. `detect_enabled`'s scenarios below reuse the exact fixture
repo + changed-file sets already exercised by
`tests/analyzers/test_registry.py` (the committed W0.8 fixture), so they
carry independent confidence: an equivalent assertion is already green
elsewhere in the suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.analyzers.pattern import PATTERN_EXCLUSIVE_GROUP
from mergecraft.analyzers.registry import (
    _PYTHON_LINT_PREFERENCE,
    _PYTHON_TYPECHECK_PREFERENCE,
    _exclusive_group_winner,
    detect_enabled,
    get_manifest,
)
from tests.analyzers.support import FIXTURE_REPO


def test_exclusive_group_winner_unchanged(tmp_path: Path) -> None:
    """`_exclusive_group_winner` (D26) and `detect_enabled` (D22)."""
    repo_root = tmp_path
    failures: list[str] = []

    def winner_id(group: str, ids: list[str], *, settings: dict[str, Any] | None = None) -> str:
        candidates = [get_manifest(i) for i in ids]
        return _exclusive_group_winner(
            group, candidates, repo_root=repo_root, settings=settings or {}
        ).id

    # -- preference ladder, no explicit override -----------------------------
    got = winner_id("python-lint", ["ruff", "pylint"])
    if got != "ruff":
        failures.append(f"python-lint[ruff,pylint] no override: winner={got!r}, expected 'ruff'")

    got = winner_id("python-lint", ["pylint"])
    if got != "pylint":
        failures.append(f"python-lint[pylint] no override: winner={got!r}, expected 'pylint'")

    got = winner_id("python-typecheck", ["mypy", "basedpyright", "pyright"])
    if got != "mypy":
        failures.append(f"python-typecheck full set: winner={got!r}, expected 'mypy'")

    got = winner_id("python-typecheck", ["basedpyright", "pyright"])
    if got != "basedpyright":
        failures.append(
            f"python-typecheck[basedpyright,pyright]: winner={got!r}, expected 'basedpyright'"
        )

    # -- exactly one explicit override wins outright, bypassing preference --
    settings_one_override = {"analyzers": {"overrides": {"pylint": {"enabled": True}}}}
    got = winner_id("python-lint", ["ruff", "pylint"], settings=settings_one_override)
    if got != "pylint":
        failures.append(
            f"single explicit override beats preference: winner={got!r}, expected 'pylint'"
        )

    # -- two explicit overrides in the same group tie-break alphabetically --
    settings_both_override = {
        "analyzers": {"overrides": {"ruff": {"enabled": True}, "pylint": {"enabled": True}}}
    }
    got = winner_id("python-lint", ["ruff", "pylint"], settings=settings_both_override)
    if got != "pylint":
        failures.append(
            f"tie-break among explicit overrides is alphabetical: winner={got!r}, expected 'pylint'"
        )

    # -- pattern-scanner group honours the configured backend ----------------
    settings_pattern = {"analyzers": {"pattern": {"backend": "opengrep"}}}
    got = winner_id(
        PATTERN_EXCLUSIVE_GROUP, ["semgrep", "opengrep", "ast-grep"], settings=settings_pattern
    )
    if got != "opengrep":
        failures.append(f"pattern-scanner backend=opengrep: winner={got!r}, expected 'opengrep'")

    # -- an unhandled group name falls back to alphabetical sort -------------
    got = winner_id("not-a-real-group", ["hadolint", "actionlint"])
    if got != "actionlint":
        failures.append(f"unhandled group default: winner={got!r}, expected 'actionlint'")

    # -- preference constants themselves (guard against silent reordering) --
    if _PYTHON_LINT_PREFERENCE != ("ruff", "pylint"):
        failures.append(f"_PYTHON_LINT_PREFERENCE drifted: {_PYTHON_LINT_PREFERENCE!r}")
    if _PYTHON_TYPECHECK_PREFERENCE != ("mypy", "basedpyright", "pyright"):
        failures.append(f"_PYTHON_TYPECHECK_PREFERENCE drifted: {_PYTHON_TYPECHECK_PREFERENCE!r}")

    # -- detect_enabled (D22): detect-match -> settings-override -> ----------
    # exclusive-group collapse, against the committed fixture repo.
    enabled = detect_enabled(
        repo_root=FIXTURE_REPO,
        changed_files=["src/example.py", "src/other.py"],
        settings_overrides={},
    )
    by_group: dict[str, list[str]] = {}
    for manifest in enabled:
        if manifest.exclusive_group:
            by_group.setdefault(manifest.exclusive_group, []).append(manifest.id)
    for group, ids in by_group.items():
        if len(ids) > 1:
            failures.append(f"detect_enabled: group {group} enabled multiple defaults: {ids}")

    enabled = detect_enabled(
        repo_root=FIXTURE_REPO,
        changed_files=["src/example.py"],
        settings_overrides={
            "analyzers": {"overrides": {"ruff": {"enabled": True}, "pylint": {"enabled": True}}}
        },
    )
    ids = {m.id for m in enabled}
    if not {"ruff", "pylint"} <= ids:
        failures.append(f"detect_enabled: explicit multi-override did not enable both: {ids}")

    enabled = detect_enabled(
        repo_root=FIXTURE_REPO, changed_files=["README.md"], settings_overrides={}
    )
    off_by_default = {m.id for m in enabled} & {"actionlint", "shellcheck", "hadolint"}
    if off_by_default:
        failures.append(
            f"detect_enabled: files with no matching detect glob enabled {off_by_default}"
        )

    assert not failures, "\n".join(failures)
