"""Approve only an App-authenticated structural verdict for a current PR head.

Run from the trusted default-branch checkout in the isolated approval job.
Exports: approve — validate provenance and submit; main — workflow entry point.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

Api = Callable[[str, dict[str, Any] | None], Any]


def approve(api: Api, *, repo: str, run: dict[str, Any], app_id: str, server: str) -> bool:
    """Validate the event, App, run, and current PR head before submitting.

    Args:
        api: Authenticated REST operation; None body means GET.
        repo: Trusted repository owner/name.
        run: workflow_run from the trusted GitHub event envelope.
        app_id: Configured App's numeric identity, never a PR-provided value.
        server: Trusted GitHub server URL used in check-run provenance.

    Returns:
        Whether a current, attributable verdict was approved.
    """
    pulls = run.get("pull_requests") or []
    if (
        not app_id.isdecimal()
        or run.get("event") != "pull_request_target"
        or run.get("conclusion") != "success"
        or run.get("repository", {}).get("full_name") != repo
        or len(pulls) != 1
    ):
        return False
    linked = pulls[0]
    number = linked.get("number")
    head = linked.get("head", {}).get("sha")
    if not isinstance(number, int) or number <= 0 or not isinstance(head, str) or not head:
        return False
    path = f"/repos/{repo}/pulls/{number}"

    def current() -> bool:
        pr = api(path, None)
        return bool(
            pr.get("state") == "open"
            and not pr.get("draft")
            and pr.get("head", {}).get("sha") == head
            and pr.get("head", {}).get("repo", {}).get("full_name") == repo
            and pr.get("base", {}).get("repo", {}).get("full_name") == repo
        )

    if not current():
        return False
    # GITHUB_RUN_ID stays the same on rerun. The start time excludes verdicts
    # from earlier attempts; details_url binds the check to this workflow run.
    started = run.get("run_started_at")
    if not isinstance(started, str) or not started or not run.get("id"):
        return False
    attempt = run.get("run_attempt")
    if not isinstance(attempt, int) or attempt <= 0:
        return False
    expected_external_id = f"{run['id']}:{attempt}"
    expected_url = f"{server.rstrip('/')}/{repo}/actions/runs/{run['id']}"
    checks = api(f"/repos/{repo}/commits/{head}/check-runs?per_page=100", None)
    candidates = [
        check
        for check in checks.get("check_runs", [])
        if check.get("name") == "mergecraft-approval"
        and str(check.get("app", {}).get("id", "")) == app_id
        and check.get("head_sha") == head
        and check.get("details_url") == expected_url
        and check.get("external_id") == expected_external_id
    ]
    if not candidates:
        return False
    latest = max(candidates, key=lambda check: check.get("id", 0))
    if (
        latest.get("status") != "completed"
        or str(latest.get("completed_at") or "") < started
        or latest.get("conclusion") != "success"
        or not current()
    ):
        return False
    api(
        f"{path}/reviews",
        {
            "event": "APPROVE",
            "commit_id": head,
            "body": f"Approved by mergeCraft — App-authenticated structural verdict on {head}.",
        },
    )
    return True


def _api(path: str, body: dict[str, Any] | None) -> Any:
    args = ["gh", "api", path]
    if body is not None:
        args += ["--method", "POST", "--input", "-"]
    result = subprocess.run(
        args,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def main() -> None:
    """Read trusted workflow context and fail closed on API/validation errors."""
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    approve(
        _api,
        repo=os.environ["GITHUB_REPOSITORY"],
        run=event["workflow_run"],
        app_id=os.environ["EXPECTED_APP_ID"],
        server=os.environ["GITHUB_SERVER_URL"],
    )


if __name__ == "__main__":
    main()
