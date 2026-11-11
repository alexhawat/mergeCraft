"""End-to-end routing boundaries for a deterministic Action image review."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import action_image_only, image_candidate_review
from tests.ci.workflow_support import REPO_ROOT, job, load_workflow


@pytest.mark.parametrize("extra", ["none", "entrypoint", "comment", "second-file", "mode", "noop"])
def test_image_only_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str) -> None:
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.invalid")
    action = Path("action.yml")
    manifest = (REPO_ROOT / action).read_bytes()
    action.write_bytes(manifest)
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    span = action_image_only.image_span(manifest)
    assert span is not None
    start, end = span
    if extra != "noop":
        action.write_bytes(
            manifest[:start] + b"docker://ghcr.io/test/image:missing" + manifest[end:]
        )
    if extra == "mode":
        action.chmod(0o755)
    if extra == "second-file":
        Path("other").write_text("extra")
    if extra == "entrypoint":
        action.write_bytes(action.read_bytes().replace(b'"/entrypoint.sh"', b'"/other.sh"'))
    if extra == "comment":
        action.write_bytes(action.read_bytes() + b"# extra\n")
    git("add", ".")
    git("commit", "--allow-empty", "-qm", "candidate")
    assert action_image_only.image_only(base, git("rev-parse", "HEAD")) == (extra == "none")


@pytest.mark.parametrize(
    ("job_result", "step_result", "current", "event"),
    [
        ("success", "success", True, "COMMENT-pass"),
        ("failure", "failure", True, "COMMENT"),
        ("success", "skipped", True, "COMMENT"),
        ("success", "success", False, None),
    ],
)
def test_review_event(
    monkeypatch: pytest.MonkeyPatch,
    job_result: str,
    step_result: str,
    current: bool,
    event: str | None,
) -> None:
    for key, value in dict(
        GITHUB_REPOSITORY="owner/repo", PR_NUMBER="7", BASE_SHA="base", HEAD_SHA="head"
    ).items():
        monkeypatch.setenv(key, value)
    pr = {"number": 7, "base": {"sha": "base"}, "head": {"sha": "head"}}
    run = {
        "id": 11,
        "run_attempt": 2,
        "path": ".github/workflows/ci.yml",
        "head_sha": "head",
        "pull_requests": [pr],
    }
    candidate = {
        "name": image_candidate_review.JOB,
        "conclusion": job_result,
        "status": "completed",
        "html_url": "https://github.com/example",
        "steps": [{"name": image_candidate_review.STEP, "conclusion": step_result}],
    }
    api = Mock(
        side_effect=[
            {"workflow_runs": [dict(run, pull_requests=[dict(pr, number=8)]), run]},
            {"jobs": [candidate]},
            {**pr, "state": "open", "draft": False, "head": {"sha": "head" if current else "new"}},
            {},
        ]
    )
    monkeypatch.setattr(image_candidate_review, "api", api)
    if event == "COMMENT-pass":
        image_candidate_review.main()
    else:
        with pytest.raises(SystemExit):
            image_candidate_review.main()
    assert api.call_args_list[1].args[0].endswith("/runs/11/attempts/2/jobs?per_page=100")
    if event:
        assert api.call_args.args[0].endswith("/pulls/7/reviews")
        assert "event=COMMENT" in api.call_args.args
        assert "event=APPROVE" not in api.call_args.args
        assert "event=REQUEST_CHANGES" not in api.call_args.args
        assert "commit_id=head" in api.call_args.args
    else:
        assert api.call_count == 3


def test_unrelated_ci_run_is_ineligible(monkeypatch: pytest.MonkeyPatch) -> None:
    pr = {"number": 7, "base": {"sha": "base"}, "head": {"sha": "head"}}
    run = {"path": ".github/workflows/ci.yml", "head_sha": "head", "pull_requests": [pr]}
    api = Mock(
        return_value={
            "workflow_runs": [
                dict(run, path=".github/workflows/other.yml"),
                dict(run, head_sha="old"),
                dict(run, pull_requests=[dict(pr, base={"sha": "old"})]),
                dict(run, pull_requests=[dict(pr, number=8)]),
            ]
        }
    )
    monkeypatch.setattr(image_candidate_review, "api", api)
    assert image_candidate_review.candidate_job("owner/repo", 7, "base", "head") is None
    assert api.call_count == 1


def test_verified_image_reviews_skip_wait_and_all_review_rungs() -> None:
    workflow = load_workflow("mergecraft.yml")
    for name in ("wait-for-ci", "review"):
        assert "needs.changes.outputs.image_only != 'true'" in job(workflow, name)["if"]
    assert "needs.review.result == 'success'" in job(workflow, "review-codex")["if"]
    assert "needs.review.result != 'skipped'" in job(workflow, "review-backstop")["if"]
    gate = job(workflow, "approval-gate")
    assert "image-review" in gate["needs"]
    assert gate["steps"][0]["env"]["RESULT"] == "${{ needs.image-review.result }}"
    assert gate["steps"][0]["run"] == 'test "$RESULT" = success'
