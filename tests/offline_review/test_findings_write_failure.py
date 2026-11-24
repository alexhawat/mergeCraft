"""A findings-write failure keeps the run's cost and is an infrastructure fault (#1561).

``write_findings_json`` can fail after a successful, paid review — a read-only
output directory, a full disk, a path below a regular file. The write failure
used to build a fresh ``OfflineReviewResult`` through ``_offline_failure``,
which dropped ``cost_usd`` and ``total_tokens`` and reported the runner fault as
``configuration_error`` (exit 30).

The contract under test:

* ``_finalize_structured_findings`` returns ``replace(result, success=False,
  error=f"failed to write findings JSON: {exc}", outcome=RunOutcome.infra_error, ...)``
  and keeps ``cost_usd``, ``total_tokens``, ``diff_path`` and
  ``evidence_packet_path``;
* the fields ``_structured_output_failure`` clears (``output`` and
  ``structured_output``) are cleared the same way;
* the empty-diff write path reports ``infra_error`` too;
* ``exit_code_for_outcome`` maps both to exit ``40``.

The failure is made with a ``json_path`` below a regular file (never with file
permissions, so the cases hold when the suite runs as root).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome, exit_code_for_outcome
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.run_bounds import resolve_run_bounds
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+import os\n"
_ERROR_PREFIX = "failed to write findings JSON"


def _blocked_findings_path(tmp_path: Path) -> Path:
    """Return a findings path whose parent directory is a regular file."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file, not a directory\n", encoding="utf-8")
    return blocker / "findings.json"


def _paid_result(tmp_path: Path) -> OfflineReviewResult:
    """A successful review that spent $1.25 and 4000 tokens."""
    diff_path = tmp_path / "change.diff"
    diff_path.write_text(_DIFF, encoding="utf-8")
    packet_path = tmp_path / "packet.json"
    packet_path.write_text("{}\n", encoding="utf-8")
    return OfflineReviewResult(
        success=True,
        output="review text",
        diff_path=str(diff_path),
        structured_output='{"findings": []}',
        evidence_packet_path=str(packet_path),
        outcome=RunOutcome.passed,
        cost_usd=1.25,
        total_tokens=4000,
        source_root=tmp_path,
        jev_judge={"calibration": "kept"},
    )


def _driver(tmp_path: Path, *, json_path: Path) -> offline_mod._OfflineDiffReviewRun:
    """A minimal offline review driver whose diff is empty."""
    diff_path = tmp_path / "empty.diff"
    diff_path.write_text("", encoding="utf-8")
    driver = offline_mod._OfflineDiffReviewRun(
        cwd=tmp_path,
        workspace=ResolvedWorkspace(cwd=tmp_path, git_common_dir=tmp_path / ".git", cloned=False),
        spec=SourceResolverSpec(cwd=tmp_path, invocation_root=tmp_path),
        out_dir=tmp_path,
        diff_file=None,
        trust_tier="trusted",
        run_bounds=resolve_run_bounds(env={}),
        analyzers_enabled=False,
        json_path=json_path,
        prompt_extra=None,
        dry_run=False,
        model=None,
        evidence_packet_path=None,
        on_finding=None,
        read_cache=False,
    )
    driver.materialization = DiffMaterialization(
        path=diff_path,
        base_ref="main",
        line_count=0,
        empty=True,
    )
    return driver


# --------------------------------------------------------------------------- findings write


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_write_failure_keeps_cost_and_tokens(tmp_path: Path) -> None:
    """#1561 — the paid run keeps its recorded cost and tokens on a write failure."""
    result = _paid_result(tmp_path)

    finished = offline_mod._finalize_structured_findings(result, _blocked_findings_path(tmp_path))

    assert finished.success is False
    assert finished.cost_usd == 1.25
    assert finished.total_tokens == 4000
    assert finished.error is not None
    assert finished.error.startswith(_ERROR_PREFIX)


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_write_failure_is_infra_error(tmp_path: Path) -> None:
    """#1561 — a write failure is a runner fault (exit 40), not operator config (30)."""
    result = _paid_result(tmp_path)

    finished = offline_mod._finalize_structured_findings(result, _blocked_findings_path(tmp_path))

    assert finished.outcome is RunOutcome.infra_error
    assert exit_code_for_outcome(finished.outcome) == 40


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_write_failure_keeps_diff_and_packet_paths(tmp_path: Path) -> None:
    """#1561 — the failure keeps every field of the result it was built from."""
    result = _paid_result(tmp_path)

    finished = offline_mod._finalize_structured_findings(result, _blocked_findings_path(tmp_path))

    assert finished.diff_path == result.diff_path
    assert finished.evidence_packet_path == result.evidence_packet_path
    assert finished.source_root == result.source_root
    assert finished.jev_judge == result.jev_judge
    # The payload that could not be written is cleared, as ``_structured_output_failure`` does.
    assert finished.output is None
    assert finished.structured_output is None


@pytest.mark.xfail(reason="green after W3", strict=True)
async def test_empty_diff_write_failure_is_infra_error(tmp_path: Path) -> None:
    """#1561 — the empty-diff write path reports infrastructure, not configuration."""
    driver = _driver(tmp_path, json_path=_blocked_findings_path(tmp_path))

    result = await driver.review()

    assert result.success is False
    assert result.outcome is RunOutcome.infra_error
    assert exit_code_for_outcome(result.outcome) == 40
    assert result.error is not None
    assert result.error.startswith(_ERROR_PREFIX)


# --------------------------------------------------------------------------- guard


def test_successful_write_returns_the_result_unchanged(tmp_path: Path) -> None:
    """Guard: a writable path still returns the same successful result."""
    result = _paid_result(tmp_path)
    json_path = tmp_path / "findings.json"

    finished = offline_mod._finalize_structured_findings(result, json_path)

    assert finished is result
    assert finished.success is True
    assert json_path.is_file()
