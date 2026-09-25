"""CodeQL must publish what it analyses and fail when the analysis fails.

The current workflow sets ``continue-on-error: true`` and ``upload: never``,
so every run is green whatever the analysis found. This module pins the end
state: no ``continue-on-error`` anywhere, an ``upload`` value conditional on a
token that can write ``security-events``, and the write permission plus
triggers kept as they are.
"""

from __future__ import annotations

from typing import Any, Final

from tests.ci.workflow_support import job, load_workflow, workflow_on

# The fork/Dependabot read-only cases the upload condition must exclude.
_FORK_CLAUSE: Final = "github.event.pull_request.head.repo.full_name == github.repository"
_DEPENDABOT_CLAUSE: Final = "github.actor != 'dependabot[bot]'"
_NON_PR_CLAUSE: Final = "github.event_name != 'pull_request'"


def _mappings(node: Any) -> list[dict[str, Any]]:
    """Every mapping nested anywhere in a parsed YAML document."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_mappings(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_mappings(value))
    return found


def _analyze_step(doc: dict[str, Any]) -> dict[str, Any]:
    analyze = job(doc, "analyze")
    for step in analyze["steps"]:
        uses = str(step.get("uses", ""))
        if uses.startswith("github/codeql-action/analyze@"):
            return step
    raise AssertionError(f"analyze job has no codeql-action/analyze step: {analyze['steps']}")


def test_analysis_failure_fails_the_job_without_gating_the_repo() -> None:
    """No ``continue-on-error``; the write permission and triggers stay put."""
    doc = load_workflow("codeql.yml")
    offenders = [mapping for mapping in _mappings(doc) if "continue-on-error" in mapping]
    assert not offenders, (
        "codeql.yml must not swallow analysis or upload failures with "
        f"continue-on-error: {offenders}"
    )

    analyze = job(doc, "analyze")
    permissions = analyze.get("permissions") or {}
    assert permissions.get("security-events") == "write", (
        "the analyse job must keep the security-events: write token"
    )

    triggers = workflow_on(doc)
    assert set(triggers["push"]["branches"]) == {"main", "pre-0.0.1"}
    assert set(triggers["pull_request"]["branches"]) == {"main", "pre-0.0.1"}
    assert triggers["schedule"], "the weekly CodeQL schedule must stay"


def test_upload_is_conditional_on_write_capable_events() -> None:
    """A fork or Dependabot PR may not upload; every other event must."""
    step = _analyze_step(load_workflow("codeql.yml"))
    upload = step.get("with", {}).get("upload")
    assert upload not in ("never", False), (
        "upload: never discards every analysis result; make it conditional on the event"
    )
    upload = str(upload)
    for clause in (_NON_PR_CLAUSE, _FORK_CLAUSE, _DEPENDABOT_CLAUSE):
        assert clause in upload, f"upload condition must name {clause!r}: {upload!r}"
    assert "'always'" in upload, (
        f"upload must resolve to always on write-capable events: {upload!r}"
    )
    assert "'never'" in upload, (
        f"upload must resolve to never on fork and Dependabot PRs: {upload!r}"
    )
