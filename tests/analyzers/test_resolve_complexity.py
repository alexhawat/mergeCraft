"""Characterisation suite for G4.1 — `analyzers/resolve.py:resolve_analyzer` (D 26).

PR G4 (`.ignorelocal/waves/issues-showcase-readiness-wave-plan.md`, "PR G4")
extracts `resolve_analyzer`'s preference ladder into per-source resolvers
behind a small dispatch table. This is a pure refactor: per G4.1's own
acceptance line, this test must be **green today**, against unmodified
code, and **stay green** after the extraction — the inverse of this repo's
usual RED-first convention.

Table-driven over `load_catalog()` — the whole bundled analyzer catalog (57
manifests at the time this test was written), the "existing catalog
fixtures" G4.1 names. Every boolean input is forced explicitly (never
`None`, which would trigger PATH auto-detection and make the outcome
environment-dependent), so the expected mode for every manifest is a pure
function of that manifest's own fields (`declared_unavailable`, `id`,
`runtime`) — computed independently below, not copied from whatever the
function under test currently returns. That makes this an oracle, not a
snapshot.
"""

from __future__ import annotations

from pathlib import Path

from mergecraft.analyzers.registry import load_catalog
from mergecraft.analyzers.resolve import _TYPE_CHECKER_IDS, resolve_analyzer

CATALOG = {m.id: m for m in load_catalog()}


def test_resolve_analyzer_behaviour_unchanged(tmp_path: Path) -> None:
    """D26's preference ladder, pinned across every catalog manifest.

    Four scenarios per manifest:

    1. Nothing available — only `declared_unavailable` manifests and the
       always-in-process `agentsec` special case resolve to anything but
       `skip`.
    2. The repo already has the tool installed — repo-native wins for
       everyone except `declared_unavailable`, which is checked first and
       short-circuits regardless of tool availability.
    3. Only mergeCraft's managed binary is available — type checkers never
       substitute a managed binary for the repo's own configured tool
       (C3/D5, `mypy`/`pyright`/`basedpyright`); every other `managed` or
       `repo-native` runtime manifest gets the managed substitute.
    4. `allow_repo_binaries=False` (the `shell: disabled` path, #35/D5) —
       forces `repo_has_tool=False` even when the caller passed `True`, so
       the outcome collapses to (3)'s ladder plus the `container` branch
       (exercised here since scenario 3 leaves it untested).
    """
    repo_root = tmp_path
    failures: list[str] = []

    for manifest_id, manifest in sorted(CATALOG.items()):
        # -- scenario 1: nothing available -----------------------------------
        plan = resolve_analyzer(
            manifest=manifest,
            repo_root=repo_root,
            repo_has_tool=False,
            ci_artifact_available=False,
            managed_available=False,
            container_available=False,
        )
        if manifest.declared_unavailable:
            expected_mode = "skip"
        elif manifest_id == "agentsec":
            expected_mode = "repo-native"
        else:
            expected_mode = "skip"
        if plan.mode != expected_mode:
            failures.append(
                f"{manifest_id} nothing-available: mode={plan.mode!r}, expected {expected_mode!r}"
            )
        if plan.mode == "skip" and not plan.reason:
            failures.append(f"{manifest_id} nothing-available: skip with no reason recorded")

        sqlfluff_needs_dialect = manifest_id == "sqlfluff"
        # tmp_path has no .sqlfluff / [tool.sqlfluff]; Finding 4 skips sqlfluff.

        # -- scenario 2: repo already has the tool installed -----------------
        plan = resolve_analyzer(
            manifest=manifest,
            repo_root=repo_root,
            repo_has_tool=True,
            repo_tool_path="/usr/local/bin/tool",
            repo_tool_version="9.9.9",
            ci_artifact_available=True,
            managed_available=True,
            container_available=True,
        )
        if manifest.declared_unavailable or sqlfluff_needs_dialect:
            expected_mode = "skip"
        else:
            expected_mode = "repo-native"
        if plan.mode != expected_mode:
            failures.append(
                f"{manifest_id} repo-has-tool: mode={plan.mode!r}, expected {expected_mode!r}"
            )
        if (
            manifest_id != "agentsec"
            and plan.mode == "repo-native"
            and (not plan.version_note or "9.9.9" not in plan.version_note)
        ):
            failures.append(
                f"{manifest_id} repo-has-tool: version_note missing repo tool version "
                f"(got {plan.version_note!r})"
            )

        # -- scenario 3: only mergeCraft's managed binary is available -------
        plan = resolve_analyzer(
            manifest=manifest,
            repo_root=repo_root,
            repo_has_tool=False,
            ci_artifact_available=False,
            managed_available=True,
            container_available=False,
        )
        if manifest.declared_unavailable or sqlfluff_needs_dialect:
            expected_mode = "skip"
        elif manifest_id == "agentsec":
            expected_mode = "repo-native"
        elif manifest_id in _TYPE_CHECKER_IDS:
            expected_mode = "skip"
        elif manifest.runtime in {"managed", "repo-native"}:
            expected_mode = "managed"
        else:
            expected_mode = "skip"
        if plan.mode != expected_mode:
            failures.append(
                f"{manifest_id} managed-only: mode={plan.mode!r}, expected {expected_mode!r}"
            )

        # -- scenario 4: allow_repo_binaries=False (shell: disabled, #35/D5) -
        plan = resolve_analyzer(
            manifest=manifest,
            repo_root=repo_root,
            repo_has_tool=True,  # ignored -- allow_repo_binaries=False overrides it
            allow_repo_binaries=False,
            ci_artifact_available=False,
            managed_available=True,
            container_available=True,
        )
        if manifest.declared_unavailable or sqlfluff_needs_dialect:
            expected_mode = "skip"
        elif manifest_id == "agentsec":
            expected_mode = "repo-native"
        elif manifest_id in _TYPE_CHECKER_IDS:
            expected_mode = "skip"
        elif manifest.runtime in {"managed", "repo-native"}:
            expected_mode = "managed"
        elif manifest.runtime == "container":
            expected_mode = "container"
        else:
            expected_mode = "skip"
        if plan.mode != expected_mode:
            failures.append(
                f"{manifest_id} shell-disabled: mode={plan.mode!r}, expected {expected_mode!r}"
            )

    assert CATALOG, "catalog loaded empty -- fixture drift, not a resolve_analyzer regression"
    assert not failures, "\n".join(failures)
