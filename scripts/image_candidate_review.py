"""Read the deployment-candidate verdict from the matching CI run and submit the review."""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

JOB = "Verify changed deployment candidates"
STEP = "Verify changed image or consumer pin"


def api(path: str, *args: str) -> Any:
    result = subprocess.run(
        ["gh", "api", path, *args], check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(result.stdout)


def candidate_job(repo: str, number: int, base: str, head: str) -> dict[str, Any] | None:
    """Read only the exact PR/base/head CI run's current attempt and verifier step."""
    runs = api(f"repos/{repo}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={head}")
    for run in runs["workflow_runs"]:
        if run["path"] != ".github/workflows/ci.yml" or run["head_sha"] != head:
            continue
        if not any(
            pr["number"] == number and pr["head"]["sha"] == head and pr["base"]["sha"] == base
            for pr in run["pull_requests"]
        ):
            continue
        jobs = api(
            f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
        )
        return next((job for job in jobs["jobs"] if job["name"] == JOB), None)
    return None


def verified(job: dict[str, Any]) -> bool:
    return job["conclusion"] == "success" and any(
        step["name"] == STEP and step["conclusion"] == "success" for step in job["steps"]
    )


def main() -> None:
    repo, number = os.environ["GITHUB_REPOSITORY"], int(os.environ["PR_NUMBER"])
    base, head = os.environ["BASE_SHA"], os.environ["HEAD_SHA"]
    deadline = time.monotonic() + 300
    passed = False
    body = "The signed image verification did not complete. Rerun CI and the review."
    while time.monotonic() < deadline:
        try:
            job = candidate_job(repo, number, base, head)
        except (subprocess.SubprocessError, OSError, ValueError):
            # Actions may briefly return a 404 while the attempt's jobs materialize.
            job = None
        if job and job["status"] == "completed":
            passed = verified(job)
            result = "passed" if passed else "failed"
            body = (
                f"Image-only manifest update. Signed image verification {result}. {job['html_url']}"
            )
            break
        time.sleep(5)

    pr = api(f"repos/{repo}/pulls/{number}")
    if (
        pr["state"] != "open"
        or pr["draft"]
        or pr["head"]["sha"] != head
        or pr["base"]["sha"] != base
    ):
        raise SystemExit("PR snapshot changed; the image verdict is stale")
    # A COMMENT review, never APPROVE/REQUEST_CHANGES: the reviewer App often authored
    # the manifest PR, and GitHub rejects an approval by the PR author. The job's own
    # exit status (the SystemExit below) is what the merge gate reads.
    event = "COMMENT"
    api(
        f"repos/{repo}/pulls/{number}/reviews",
        "-f",
        f"event={event}",
        "-f",
        f"commit_id={head}",
        "-f",
        f"body={body}",
    )
    if not passed:
        raise SystemExit(body)


if __name__ == "__main__":
    main()
