"""Quickstart smoke: pure logic of ``scripts/quickstart_smoke.py`` and its workflow policy."""

from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, load_workflow, workflow_on

WORKFLOW = "quickstart-smoke.yml"
SHA = "a" * 40
BOT = {"login": "github-actions[bot]", "type": "Bot"}
HUMAN = {"login": "alexhawat", "type": "User"}


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    return importlib.import_module("quickstart_smoke")


def _run(**over: Any) -> dict[str, Any]:
    base = {
        "head_sha": SHA,
        "path": ".github/workflows/mergecraft.yml",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-11-12T01:00:00Z",
        "html_url": "https://github.com/o/r/actions/runs/1",
    }
    return {**base, **over}


# ---- argument handling ----------------------------------------------------------------


def test_run_defaults_follow_the_published_release(smoke: Any) -> None:
    args = smoke.parse_args(["run"])
    assert (args.command, args.install, args.repo) == ("run", "release", smoke.DEFAULT_REPO)


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--install", "both"],
        ["run", "--repo", "not-a-slug"],
        ["run", "--timeout", "0"],
        ["run", "--run-id", "a b"],
        ["cleanup", "--repo", "x/y/z"],
        [],
    ],
    ids=["unknown-install", "bad-repo", "zero-timeout", "bad-run-id", "bad-cleanup-repo", "no-cmd"],
)
def test_bad_arguments_exit_2(smoke: Any, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        smoke.parse_args(argv)
    assert exc.value.code == 2


def test_readme_install_spec_reads_the_quickstart_pin(smoke: Any) -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert smoke.readme_install_spec(readme).startswith("mergecraft-action==")


def test_readme_install_spec_ignores_other_sections_and_honours_override(smoke: Any) -> None:
    text = "# T\n\n## Install\nuv tool install mergecraft-action==9.9\n\n## Quickstart\nnothing\n\n## X\n"
    with pytest.raises(smoke.SmokeError):
        smoke.readme_install_spec(text)
    assert smoke.readme_install_spec(text, "1.2.3") == "mergecraft-action==1.2.3"


def test_branch_name_is_under_the_cleanup_prefix(smoke: Any) -> None:
    assert smoke.branch_name("42", "source").startswith(smoke.BRANCH_PREFIX)


# ---- was a review posted --------------------------------------------------------------


def test_review_posted_sees_bot_review_and_comments(smoke: Any) -> None:
    reviews = [{"id": 1, "state": "COMMENTED", "user": BOT}]
    assert smoke.review_posted(reviews, [], []) == ["review 1 (COMMENTED)"]
    assert smoke.review_posted([], [{"id": 2, "user": BOT}], []) == ["issue comment 2"]
    assert smoke.review_posted([], [], [{"id": 3, "user": BOT}]) == ["review comment 3"]


@pytest.mark.parametrize(
    ("reviews", "issue", "inline"),
    [
        ([], [], []),
        ([{"id": 1, "state": "COMMENTED", "user": HUMAN}], [{"id": 2, "user": HUMAN}], []),
        ([{"id": 1, "state": "PENDING", "user": BOT}], [], []),
        ([{"id": 1, "state": "COMMENTED", "user": None}], [{"id": 2}], []),
    ],
    ids=["empty", "human-only", "pending-draft", "ghost-user"],
)
def test_review_posted_rejects_non_reviews(
    smoke: Any, reviews: list[Any], issue: list[Any], inline: list[Any]
) -> None:
    assert smoke.review_posted(reviews, issue, inline) == []


# ---- did the run conclude / verdict ---------------------------------------------------


@pytest.mark.parametrize(
    ("runs", "state"),
    [
        ([], "missing"),
        ([_run(head_sha="b" * 40)], "missing"),
        ([_run(path=".github/workflows/other.yml")], "missing"),
        ([_run(event="push")], "missing"),
        ([_run(status="in_progress", conclusion=None)], "running"),
        ([_run()], "concluded"),
        ([_run(conclusion="failure")], "concluded"),
        ([_run(conclusion="cancelled")], "bad"),
        ([_run(conclusion="skipped")], "bad"),
        ([_run(conclusion="failure", created_at="1"), _run(created_at="2")], "concluded"),
        ([_run(created_at="1"), _run(status="queued", conclusion=None, created_at="2")], "running"),
    ],
    ids=[
        "none",
        "other-sha",
        "other-workflow",
        "other-event",
        "running",
        "success",
        "failure",
        "cancelled",
        "skipped",
        "newest-wins",
        "newest-running",
    ],
)
def test_run_outcome(smoke: Any, runs: list[Any], state: str) -> None:
    assert smoke.run_outcome(runs, SHA)[0] == state


def test_evaluate_passes_only_with_review_and_concluded_run(smoke: Any) -> None:
    review = [{"id": 1, "state": "COMMENTED", "user": BOT}]
    ok = smoke.evaluate([_run()], review, [], [], SHA)
    assert (ok.ok, ok.done) == (True, True)
    assert ok.run_url.endswith("/runs/1")

    no_review = smoke.evaluate([_run()], [], [], [], SHA)
    assert (no_review.ok, no_review.done) == (False, True)
    assert "no review" in no_review.message

    pending = smoke.evaluate([], review, [], [], SHA)
    assert (pending.ok, pending.done) == (False, False)

    bad = smoke.evaluate([_run(conclusion="cancelled")], review, [], [], SHA)
    assert (bad.ok, bad.done) == (False, True)


def test_evaluate_notes_a_failed_gate_after_a_posted_review(smoke: Any) -> None:
    review = [{"id": 1, "state": "COMMENTED", "user": BOT}]
    verdict = smoke.evaluate([_run(conclusion="failure")], review, [], [], SHA)
    assert verdict.ok
    assert "final gate failed" in verdict.message


# ---- bounded polling ------------------------------------------------------------------


def test_wait_for_review_is_bounded(smoke: Any) -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    verdict = smoke.wait_for_review(
        lambda: smoke.Verdict(False, False, "review run running", "u"),
        timeout=50,
        interval=20,
        sleep=sleep,
        clock=lambda: now[0],
    )
    assert not verdict.ok
    assert verdict.done
    assert "timed out" in verdict.message
    assert sum(sleeps) <= 50


def test_wait_for_review_returns_as_soon_as_done(smoke: Any) -> None:
    answers = iter([smoke.Verdict(False, False, "x"), smoke.Verdict(True, True, "y")])
    verdict = smoke.wait_for_review(
        lambda: next(answers), timeout=100, interval=1, sleep=lambda _s: None
    )
    assert verdict.ok


# ---- redaction ------------------------------------------------------------------------


def test_redact_removes_secret_values_and_token_shapes(smoke: Any) -> None:
    text = "key=supersecretvalue token=ghp_" + "A" * 30 + " pat=github_pat_" + "B" * 30
    out = smoke.redact(text, ["supersecretvalue"])
    assert "supersecretvalue" not in out
    assert "ghp_" not in out
    assert "github_pat_" not in out


# ---- cleanup ordering -----------------------------------------------------------------


class _FakeRunner:
    """Records gh calls and answers the listing endpoints with canned payloads."""

    def __init__(self, fail_on: str = "") -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        joined = " ".join(argv)
        if self.fail_on and self.fail_on in joined:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        out = ""
        if "pulls?state=open" in joined:
            out = json.dumps(
                [
                    {"number": 7, "head": {"ref": "smoke/1-release"}},
                    {"number": 8, "head": {"ref": "feature/keep"}},
                ]
            )
        elif "matching-refs" in joined:
            out = json.dumps([{"ref": "refs/heads/smoke/1-release"}])
        elif "actions/secrets?" in joined:
            out = json.dumps(
                {"secrets": [{"name": "LLM_PROVIDER_1_API_KEY"}, {"name": "UNRELATED"}]}
            )
        return subprocess.CompletedProcess(argv, 0, out, "")


def _ctx(smoke: Any, runner: _FakeRunner) -> Any:
    return smoke.Context(
        repo="o/r", token="tok-value", api_key="key-value", runner=runner, log=lambda _m: None
    )


def _kinds(calls: list[list[str]]) -> list[str]:
    kinds = []
    for argv in calls:
        joined = " ".join(argv)
        if "-X PATCH repos/o/r/pulls/7" in joined:
            kinds.append("close_pr")
        elif "-X DELETE" in joined:
            kinds.append("delete_branch")
        elif "-X PATCH repos/o/r/git/refs/heads/main" in joined:
            kinds.append("reset_main")
        elif argv[:3] == ["gh", "secret", "delete"]:
            kinds.append(f"delete_secret:{argv[3]}")
    return kinds


def test_cleanup_order_and_scope(smoke: Any) -> None:
    runner = _FakeRunner()
    assert smoke.cleanup(_ctx(smoke, runner), "c" * 40) == []
    assert _kinds(runner.calls) == [
        "close_pr",
        "delete_branch",
        "reset_main",
        "delete_secret:LLM_PROVIDER_1_API_KEY",
    ]
    assert smoke.cleanup_plan() == [
        "close_pull_requests",
        "delete_branches",
        "reset_main",
        "delete_secrets",
    ]
    reset = next(c for c in runner.calls if "git/refs/heads/main" in " ".join(c))
    assert f"sha={'c' * 40}" in reset


def test_cleanup_keeps_going_after_a_failed_step_and_reports_it(smoke: Any) -> None:
    runner = _FakeRunner(fail_on="-X DELETE")
    errors = smoke.cleanup(_ctx(smoke, runner), "c" * 40)
    assert len(errors) == 1
    assert errors[0].startswith("delete_branches")
    assert _kinds(runner.calls) == [
        "close_pr",
        "delete_branch",  # attempted (and failed), then the run carried on
        "reset_main",
        "delete_secret:LLM_PROVIDER_1_API_KEY",
    ]


def test_secrets_never_reach_argv(smoke: Any) -> None:
    runner = _FakeRunner()
    smoke.cleanup(_ctx(smoke, runner), "c" * 40)
    assert all("tok-value" not in a and "key-value" not in a for argv in runner.calls for a in argv)


def test_cleanup_without_state_is_a_noop(
    smoke: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMOKE_REPO_TOKEN", "t")
    assert smoke.main(["cleanup", "--state", str(tmp_path / "missing.json")]) == 0


def test_missing_secrets_are_an_error_for_the_script(
    smoke: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMOKE_REPO_TOKEN", raising=False)
    monkeypatch.delenv("SMOKE_PROVIDER_API_KEY", raising=False)
    assert smoke.main(["run"]) == 2


# ---- workflow policy ------------------------------------------------------------------


def test_workflow_is_not_reachable_from_pull_request_events() -> None:
    triggers = set(workflow_on(load_workflow(WORKFLOW)))
    assert triggers == {"schedule", "workflow_dispatch", "workflow_call"}


def test_workflow_hardening_and_secret_gate() -> None:
    doc = load_workflow(WORKFLOW)
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"]["cancel-in-progress"] is False
    job = doc["jobs"]["smoke"]
    assert job["timeout-minutes"] <= 60
    steps = job["steps"]
    gate = steps[0]
    assert gate["id"] == "gate"
    assert "::notice" in gate["run"]
    assert "exit 1" not in gate["run"]
    for step in steps[1:]:
        assert "steps.gate.outputs.enabled == 'true'" in step["if"]
    assert steps[-1]["if"].startswith("always()")
    assert "cleanup" in steps[-1]["run"]


def test_workflow_secrets_only_flow_through_env() -> None:
    doc = load_workflow(WORKFLOW)
    for step in doc["jobs"]["smoke"]["steps"]:
        assert "secrets." not in str(step.get("run", ""))
    text = (REPO_ROOT / ".github" / "workflows" / WORKFLOW).read_text(encoding="utf-8")
    assert "pull_request" not in "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
