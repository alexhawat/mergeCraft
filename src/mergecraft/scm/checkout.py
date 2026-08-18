"""Checkout helpers routed through ``ScmProvider`` (DG9)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.checkout import changed_paths_in_diff

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider


def checkout_pull_request(
    provider: ScmProvider,
    *,
    owner: str,
    repo: str,
    pull_number: int,
    cwd: str,
    temp_dir: str,
    last_reviewed_sha: str | None = None,
) -> dict[str, Any]:
    """Write PR diff artifacts from provider-held diff text (test seam).

    Production checkouts continue to run through ``mcp/checkout.py``; this
    helper preserves incremental diff semantics for protocol-level tests.
    """
    _ = (owner, repo, cwd)
    diff_text = str(getattr(provider, "diff_text", "") or "")
    incremental_text = getattr(provider, "incremental_diff_text", None)

    diff_path = str(Path(temp_dir) / f"pr-{pull_number}.diff")
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    Path(diff_path).write_text(diff_text, encoding="utf-8")

    result: dict[str, Any] = {
        "pullNumber": pull_number,
        "diffPath": diff_path,
    }

    if last_reviewed_sha:
        inc_body = str(incremental_text if incremental_text is not None else diff_text)
        incremental_path = str(Path(temp_dir) / f"pr-{pull_number}-incremental.diff")
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        Path(incremental_path).write_text(inc_body, encoding="utf-8")
        result["incrementalDiffPath"] = incremental_path
        result["lastReviewedSha"] = last_reviewed_sha
        result["incrementalChangedPaths"] = changed_paths_in_diff(inc_body)

    return result
