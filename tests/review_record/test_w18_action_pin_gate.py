"""W1.8 — action pin gate wired into ci-static (#532, implementation W8)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text, workflow_on
from tests.pins.test_action_pin_freshness import _load, _workflow_text

_SHA_A = "0592d72828797005fdc5af1da9e413b0a98bd8a0"
_SHA_B = "cfa36704cf6c58a6abe895e539a377c4599fa4bd"
_WORKFLOW = ".github/workflows/mergecraft.yml"
_STALENESS_WORKFLOW = "action-pin-staleness.yml"


def _makefile_text() -> str:
    return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def _recipe(target: str) -> str:
    """Return the tab-indented recipe body for one Makefile target."""
    lines = _makefile_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    return "\n".join(body)


def test_make_ci_static_invokes_action_pin_check() -> None:
    makefile = _makefile_text()
    ci_static_line = next(line for line in makefile.splitlines() if line.startswith("ci-static:"))
    assert "action-pin-check" in ci_static_line
    ci_steps = next(line for line in makefile.splitlines() if line.startswith("CI_STEPS :="))
    assert "action-pin-check" in ci_steps


def test_the_required_gate_carries_no_rule_a_pull_request_cannot_satisfy() -> None:
    """#669: staleness on the PR gate froze the whole queue behind main's debt.

    ``action-pin-staleness-check`` must stay out of the tiers wired to the
    required ``Verify (static + build)`` check, or one stale pin on main fails
    every open PR again — including the manifest PR that would fix it.
    """
    makefile = _makefile_text()
    ci_static_line = next(line for line in makefile.splitlines() if line.startswith("ci-static:"))
    ci_steps = next(line for line in makefile.splitlines() if line.startswith("CI_STEPS :="))
    assert "action-pin-staleness-check" not in ci_static_line
    assert "action-pin-staleness-check" not in ci_steps


def test_the_two_targets_select_the_scopes_they_claim() -> None:
    assert "--scope pr" in _recipe("action-pin-check")
    assert "--scope all" in _recipe("action-pin-staleness-check")


def test_staleness_runs_on_a_schedule_never_on_a_pull_request() -> None:
    triggers = workflow_on(load_workflow(_STALENESS_WORKFLOW))
    assert "schedule" in triggers, "staleness has no owner if nothing schedules it"
    assert "workflow_dispatch" in triggers, "an operator must be able to re-check on demand"
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers


def test_the_staleness_workflow_runs_the_full_scope_and_can_file_an_issue() -> None:
    """Moving a rule off the PR gate only works if something still reports it."""
    text = read_text(f".github/workflows/{_STALENESS_WORKFLOW}")
    assert "make action-pin-staleness-check" in text

    staleness = job(load_workflow(_STALENESS_WORKFLOW), "staleness")
    permissions = staleness["permissions"]
    assert permissions["issues"] == "write", "cannot report a stale pin without issues: write"
    assert permissions["contents"] == "read", "the reporter never needs write access to the tree"


def test_the_staleness_workflow_does_not_shallow_fetch_the_default_branch() -> None:
    """A depth-limited fetch silently defangs the staleness guard.

    ``--depth=1`` marks ``origin/main`` as a shallow boundary, so
    ``_check_staleness``'s ``rev-list --count <pin>..origin/main`` stops at the
    graft and under-reports the product lag — measured on this repo, 5 commits
    read as 1. This job is now the only place that rule runs, so a silent
    under-count is the one failure that makes it useless while still reporting
    OK.
    """
    staleness = job(load_workflow(_STALENESS_WORKFLOW), "staleness")
    runs = "\n".join(str(step.get("run", "")) for step in staleness["steps"])
    fetches = [line.strip() for line in runs.splitlines() if line.strip().startswith("git fetch")]
    assert fetches, f"staleness job no longer fetches the default branch:\n{runs}"
    for line in fetches:
        assert "--depth" not in line, f"depth-limited fetch defeats the staleness guard: {line}"
        assert "--shallow-since" not in line, f"shallow fetch defeats the staleness guard: {line}"


def test_ci_yml_fails_on_pin_defects_instead_of_warning_only() -> None:
    """The PR gate must break the build, not emit a ``::warning`` nobody reads.

    Renamed from ``..._on_stale_pin_...``: ci.yml no longer runs the staleness
    rule at all (#669), so a name promising that was a lie about coverage. The
    property being guarded is unchanged and still real — the rules ci.yml *does*
    run are hard failures. Staleness gets the same treatment one test down, in
    the job that now owns it.
    """
    ci_yml = read_text(".github/workflows/ci.yml")
    assert 'echo "::warning title=mergecraft action pin drift::' not in ci_yml
    assert "make action-pin-check" in ci_yml
    assert "exit 1" in ci_yml or "exit $?" in ci_yml


def test_the_staleness_workflow_reports_a_stale_pin_instead_of_warning_only() -> None:
    """Moving the rule must not downgrade it to a log line in a job nobody opens."""
    text = read_text(f".github/workflows/{_STALENESS_WORKFLOW}")
    assert "::warning" not in text, "a scheduled job's warning annotation reaches nobody"

    steps = job(load_workflow(_STALENESS_WORKFLOW), "staleness")["steps"]
    filing = [step for step in steps if "gh issue create" in str(step.get("run", ""))]
    assert filing, "a stale pin produces no durable report"
    assert "stale == 'true'" in str(filing[0].get("if", "")), (
        "the reporting step must be gated on the measurement, not run unconditionally"
    )


def test_the_staleness_job_only_ever_speaks_for_main() -> None:
    """``workflow_dispatch`` accepts any branch; this job must not believe one.

    It reads the pin from the tree it checks out. Dispatched from a pin-bump
    branch, that pin is *ahead* of main, ``_check_staleness`` returns clean for
    the "bumped here, not yet promoted" case, and the close step would resolve
    the tracking issue while main is still stale — silently retiring a live
    alert.
    """
    staleness = job(load_workflow(_STALENESS_WORKFLOW), "staleness")
    assert staleness.get("if") == "github.ref == 'refs/heads/main'"


def test_staleness_is_measured_when_debt_lands_not_only_once_a_day() -> None:
    """Cron alone leaves the queue un-flagged for up to a day after a merge.

    GitHub's scheduler is best-effort — routinely late, skipped entirely under
    load — so a push trigger on main is what makes this timely; the cron is the
    backstop for a pin that goes stale because main moved under it.
    """
    triggers = workflow_on(load_workflow(_STALENESS_WORKFLOW))
    assert "push" in triggers, "debt is not reported until the next cron"
    assert triggers["push"]["branches"] == ["main"]


def test_mergecraft_workflow_three_rungs_share_one_pin_value() -> None:
    text = read_text(_WORKFLOW)
    pins = re.findall(r"uses:\s+alexhawat/mergeCraft@([0-9a-f]{40})", text)
    assert len(pins) >= 3
    assert len(set(pins)) == 1


def test_partial_pin_bump_fails_action_pin_check(tmp_path: Path) -> None:
    module = _load()
    drifted = tmp_path / "mergecraft.yml"
    drifted.write_text(_workflow_text(_SHA_A, _SHA_B), encoding="utf-8")
    pins = module._pins_in(drifted.read_text(encoding="utf-8"))
    failures = module._check_self_consistency(_WORKFLOW, pins)
    assert failures
    assert "different Action pins" in failures[0]


_BUMP_WORKFLOW = "bump-action-pin.yml"


def test_the_pin_bump_workflow_has_both_cycle_stages() -> None:
    """The cycle is two commits and cannot be one PR.

    P must name manifest commit C, and C's SHA is unknown until it merges, so
    the automation has to expose the stages separately rather than pretend the
    cycle is atomic.
    """
    doc = load_workflow(_BUMP_WORKFLOW)
    triggers = workflow_on(doc)
    assert "workflow_dispatch" in triggers
    stage = triggers["workflow_dispatch"]["inputs"]["stage"]
    assert set(stage["options"]) == {"manifest", "pin"}


def test_the_pin_bump_workflow_verifies_the_image_before_committing() -> None:
    """A digest nobody checked must never reach action.yml."""
    text = read_text(f".github/workflows/{_BUMP_WORKFLOW}")
    assert "make action-images-resolve" in text, "digest is not verified against GHCR"
    assert "make action-manifest-prepare" in text
    assert "make action-pin-prepare" in text


def test_the_pin_bump_workflow_does_not_open_its_own_pull_request() -> None:
    """A GITHUB_TOKEN-opened PR triggers no `pull_request` workflows.

    It would arrive with zero required checks — and the pin is precisely the
    change that must not merge unchecked. The workflow pushes a branch and
    leaves the PR to a human rather than introducing a PAT to route around it.
    """
    text = read_text(f".github/workflows/{_BUMP_WORKFLOW}")
    mentions = [line.strip() for line in text.splitlines() if "gh pr create" in line]
    assert mentions, "the workflow should still tell the operator what to run"
    for line in mentions:
        # Echoed into the job summary, or described in a comment — never run.
        assert line.startswith(("echo ", "#")), (
            f"workflow executes `gh pr create`; that PR would carry no required checks: {line}"
        )


def test_the_pin_bump_workflow_warns_against_squashing_the_manifest() -> None:
    """Squashing C orphans it and leaves nothing for P to name (#684)."""
    text = read_text(f".github/workflows/{_BUMP_WORKFLOW}")
    assert "squash" in text.lower(), "no squash warning for the manifest stage"


def test_the_pin_stage_does_not_resolve_the_image_from_mains_tip() -> None:
    """By the pin stage, main's tip is never the source the image was built from.

    The manifest PR's own merge advances main, so `stage=pin` resolving from
    HEAD asked GHCR for a digest tagged with the merge commit and always got
    nothing:

        {"analyzers_digest": "", "slim_digest": ""}
        no published slim image for e2da18fc… — wait for CI/CD to finish

    It is redundant as well as wrong: `action-pin-prepare` runs
    `verify_manifest(manifest_commit)` internally, which verifies the digest
    against GHCR for the correct source.
    """
    steps = job(load_workflow(_BUMP_WORKFLOW), "prepare")["steps"]
    resolve = [step for step in steps if "action-images-resolve" in str(step.get("run", ""))]
    assert len(resolve) == 1, "expected exactly one image-resolve step"
    guard = str(resolve[0].get("if", ""))
    assert "manifest" in guard, (
        f"image resolution is not restricted to the manifest stage: {guard!r}"
    )


def test_the_pin_stage_names_its_branch_from_the_manifest_commit() -> None:
    """The pin branch must not depend on the skipped resolve step's outputs."""
    text = read_text(f".github/workflows/{_BUMP_WORKFLOW}")
    assert "chore/action-pin-${MANIFEST_COMMIT" in text, (
        "pin branch name derives from a step that does not run in this stage"
    )
