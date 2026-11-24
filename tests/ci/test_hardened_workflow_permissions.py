"""The hardened workflow grants only the scopes mergeCraft uses (#1567).

The template sold as *hardened* once granted ``statuses: write`` under the
comment about check-runs. mergeCraft posts its ``mergecraft`` /
``mergecraft-approval`` results as **check-runs** (``utils/status_checks.py``,
``POST /repos/{owner}/{repo}/check-runs``), which need ``checks: write`` only;
the commit-status API is never called in production (the sole
``.create_status(`` call sits behind the ``scm/github.py`` wrapper with no
production caller). Commit statuses are what branch protection matches on, so
an unused write scope in a copy-me template is a real privilege leak.

Three surfaces carry the grant and all three must stay least-privilege:

* ``scripts/example_workflows/hardened.yml.tpl`` — the source template, read
  through the real renderer so the check sees the YAML a consumer copies;
* ``examples/workflows/mergecraft-hardened.yml`` — its generated copy;
* ``docs/artifacts/dogfood-mergecraft.yml`` — the hand-kept mirror.

The two unmarked guards keep the test honest: ``checks: write`` must survive
(dropping it would break check-run publication), and no *new* permission may
appear in any of the three files while the scope is removed.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from scripts.render_example_workflows import render_all

from tests.ci.workflow_support import REPO_ROOT

# The surfaces that carry the hardened grant, keyed by the label the failure
# message uses. ``template`` is rendered, not read raw, so the placeholders are
# substituted exactly as ``make examples`` substitutes them.
_HARDENED_SURFACES = (
    "template:scripts/example_workflows/hardened.yml.tpl",
    "example:examples/workflows/mergecraft-hardened.yml",
    "dogfood:docs/artifacts/dogfood-mergecraft.yml",
)

# Every permission key these three files may declare. Pinned so a removal cannot
# buy its green with an addition elsewhere. ``security-events`` is commented out
# in the template today; it is listed because the template documents it as the
# opt-in scope and a consumer uncomments it.
_ALLOWED_PERMISSION_KEYS = frozenset(
    {
        "contents",
        "actions",
        "pull-requests",
        "issues",
        "checks",
        # statuses — removed by #1567; kept out of the allow-list deliberately.
        "security-events",
    }
)


def _render_hardened_template() -> dict[str, Any]:
    """Render the hardened template through the generator and parse the YAML."""
    body = render_all()["hardened"]
    loaded = yaml.safe_load(body)
    assert isinstance(loaded, dict), "the rendered hardened template did not parse as a mapping"
    return loaded


def _load_surface(spec: str) -> dict[str, Any]:
    """Return the parsed workflow for one ``label:path`` spec.

    The template is rendered through ``scripts.render_example_workflows.py`` so
    the assertion runs on the same bytes ``make examples`` writes; the two
    committed copies are read from disk.
    """
    label, _, relative = spec.partition(":")
    assert relative, f"malformed surface spec {spec!r}"
    if label == "template":
        return _render_hardened_template()
    path = REPO_ROOT / relative
    assert path.is_file(), f"missing {relative}"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{relative} did not parse as a mapping"
    return loaded


def _permission_mappings(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return every ``permissions:`` mapping at workflow and job level.

    ``permissions: read-all`` / ``write-all`` are strings, not mappings; they
    cannot name ``statuses``, so they are skipped. A workflow that declared no
    permissions block at all yields an empty list and fails the grant guard
    below with "no permissions mapping", which is the honest failure.
    """
    mappings: list[tuple[str, dict[str, Any]]] = []
    workflow_level = doc.get("permissions")
    if isinstance(workflow_level, dict):
        mappings.append(("workflow", workflow_level))
    jobs = doc.get("jobs")
    if isinstance(jobs, dict):
        for job_name, job in jobs.items():
            block = job.get("permissions") if isinstance(job, dict) else None
            if isinstance(block, dict):
                mappings.append((f"job {job_name}", block))
    return mappings


def _permission_keys(doc: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for _, block in _permission_mappings(doc):
        keys.update(str(key) for key in block)
    return keys


@pytest.mark.xfail(reason="green after W2", strict=True)
@pytest.mark.parametrize("spec", _HARDENED_SURFACES)
def test_hardened_workflows_do_not_grant_statuses_write(spec: str) -> None:
    """No ``permissions`` mapping in the template or either copy names ``statuses`` (#1567)."""
    _, _, relative = spec.partition(":")
    doc = _load_surface(spec)
    mappings = _permission_mappings(doc)
    assert mappings, f"{relative}: no workflow-level or job-level permissions mapping to check"
    granted = {
        f"{scope}: {key}={value}"
        for scope, block in mappings
        for key, value in block.items()
        if str(key).strip() == "statuses"
    }
    assert not granted, (
        f"{relative}: the hardened workflow grants an unused statuses scope "
        f"({sorted(granted)}); mergeCraft posts check-runs (checks: write) and never "
        "calls the commit-status API"
    )


@pytest.mark.parametrize("spec", _HARDENED_SURFACES)
def test_hardened_workflows_grant_checks_write(spec: str) -> None:
    """The scope mergeCraft actually uses survives the removal (#1567)."""
    label, _, relative = spec.partition(":")
    doc = _load_surface(spec)
    checks = {
        str(block.get("checks")).strip().lower()
        for _, block in _permission_mappings(doc)
        if "checks" in block
    }
    assert "write" in checks, (
        f"{relative}: {label} must keep `checks: write` — mergeCraft posts the "
        f"mergecraft / mergecraft-approval results as check-runs; found {sorted(checks)}"
    )


@pytest.mark.xfail(reason="green after W2", strict=True)
@pytest.mark.parametrize("spec", _HARDENED_SURFACES)
def test_no_permission_was_added(spec: str) -> None:
    """Removing a scope must not add another: every key stays inside the pinned set."""
    _, _, relative = spec.partition(":")
    doc = _load_surface(spec)
    keys = _permission_keys(doc)
    assert keys, f"{relative}: no permission keys found to compare"
    unexpected = keys - _ALLOWED_PERMISSION_KEYS
    assert not unexpected, (
        f"{relative}: unexpected permission key(s) {sorted(unexpected)}; the hardened "
        f"workflow may declare only {sorted(_ALLOWED_PERMISSION_KEYS)}"
    )
