"""The documented release workflow can produce the dist artifact (#1004).

``release.yml`` prepares and pushes the release branch with the workflow's own
``GITHUB_TOKEN``. GitHub does not start workflows from a ``GITHUB_TOKEN`` push,
so the build pipeline never runs for that branch, and ``build-dist`` was gated on
a ``push`` event, so a manual dispatch skipped it too. The publish step then had
no ``artifact-python-dist`` to publish from.

These tests pin the two halves of the fix: ``build-dist`` accepts a dispatch on a
release ref, and ``release.yml`` dispatches the CI/CD workflow on the branch it
just prepared. They parse the workflow files; they never run the release.
"""

from __future__ import annotations

import re
from typing import Any

from tests.ci.workflow_support import job, load_workflow, workflow_on

_CI_CD = "ci-cd.yml"
_RELEASE = "release.yml"


def _condition(doc: dict[str, Any], name: str) -> str:
    return " ".join(str(job(doc, name).get("if", "")).split())


def test_ci_cd_keeps_every_existing_trigger() -> None:
    triggers = workflow_on(load_workflow(_CI_CD))
    assert isinstance(triggers, dict)
    assert {"push", "workflow_dispatch"} <= set(triggers)
    assert "release/**" in triggers["push"]["branches"]
    assert "v*" in triggers["push"]["tags"]


def test_build_dist_runs_for_a_dispatch_on_a_release_ref() -> None:
    condition = _condition(load_workflow(_CI_CD), "build-dist")
    assert "github.event_name == 'workflow_dispatch'" in condition, (
        f"a dispatch must be able to build the dist; condition was {condition!r}"
    )
    assert "refs/heads/release/" in condition
    assert "refs/tags/v" in condition


def test_build_dist_still_runs_for_a_push_on_a_release_ref() -> None:
    condition = _condition(load_workflow(_CI_CD), "build-dist")
    assert "github.event_name == 'push'" in condition


def test_build_dist_does_not_run_for_a_dispatch_on_an_ordinary_branch() -> None:
    """The dist is a release artifact: ``main`` must not start producing one."""
    condition = _condition(load_workflow(_CI_CD), "build-dist")
    ref_tests = re.findall(r"startsWith\(github\.ref, '([^']+)'\)", condition)
    assert set(ref_tests) == {"refs/heads/release/", "refs/tags/v"}, ref_tests
    assert "refs/heads/main" not in condition
    assert "refs/heads/pre-0.0.1" not in condition


def test_release_workflow_dispatches_the_build_on_the_prepared_branch() -> None:
    doc = load_workflow(_RELEASE)
    dispatchers = []
    for name, value in (doc.get("jobs") or {}).items():
        if not isinstance(value, dict):
            continue
        steps = value.get("steps") or []
        blob = " ".join(str(step.get("run", "")) for step in steps if isinstance(step, dict))
        if "workflow run" in blob and "ci-cd.yml" in blob:
            dispatchers.append((name, value, blob))
    assert dispatchers, "release.yml never dispatches ci-cd.yml for the branch it prepared"
    name, value, blob = dispatchers[0]
    needs = value.get("needs")
    needed = needs if isinstance(needs, list) else [needs]
    assert "prepare" in needed, f"{name} must run after prepare so the branch exists"
    assert "needs.prepare.outputs.branch" in blob or "PREPARED_BRANCH" in blob, (
        "the dispatch must target the branch prepare produced"
    )
    assert "--ref" in blob


def test_release_dispatch_holds_only_actions_write() -> None:
    """Dispatching a workflow needs ``actions: write`` — nothing else, no secrets."""
    doc = load_workflow(_RELEASE)
    for name, value in (doc.get("jobs") or {}).items():
        if not isinstance(value, dict):
            continue
        blob = " ".join(
            str(step.get("run", "")) for step in value.get("steps") or [] if isinstance(step, dict)
        )
        if "workflow run" not in blob:
            continue
        permissions = value.get("permissions") or {}
        assert permissions.get("actions") == "write", f"{name}: {permissions!r}"
        assert set(permissions) <= {"actions", "contents"}, (
            f"{name} dispatches a build and must not gain write scopes: {permissions!r}"
        )
        assert permissions.get("contents", "read") == "read"
        assert "secrets." not in str(value), f"{name} must not reference repository secrets"


def test_release_process_doc_names_the_dispatch_path() -> None:
    from tests.ci.workflow_support import read_text

    text = read_text("docs/release-process.md")
    assert "workflow_dispatch" in text or "dispatch" in text.lower()
    assert "artifact-python-dist" in text
