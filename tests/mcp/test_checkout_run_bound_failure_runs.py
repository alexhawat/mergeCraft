"""A self-review run that requested changes still moves the run-bound checkpoint.

A self-review run that does not approve finishes with conclusion ``failure`` (its gate
step fails). In the commonest loop — review requests changes, the author pushes a fix,
the review runs again — the previous run used to be skipped, so the re-review had no
checkpoint, started at round 0 and read the whole PR again. Trust comes from the event
(``pull_request_target``) and the workflow path, not from the conclusion. What a run must
carry is an evidence artefact naming ``reviewed_head_sha``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout_run_bound_checkpoint import (
    _PR_NUMBER,
    _WORKFLOW,
    _ActionsScm,
    _artifact,
    _capture_warnings,
    _packet_zip,
    _recover,
    _run,
    _scm_with_runs,
    _trusted_run,
)

if TYPE_CHECKING:
    from pathlib import Path


def _failure_run(
    *, run_id: int, head_sha: str, progress_comment_id: int | None, created_at: str
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    return (
        _run(run_id, conclusion="failure", created_at=created_at),
        _artifact(artifact_id=run_id * 10),
        _packet_zip(reviewed_head_sha=head_sha, progress_comment_id=progress_comment_id),
    )


async def test_a_failure_run_with_an_artefact_yields_a_checkpoint(tmp_path: Path) -> None:
    scm = _scm_with_runs(
        [
            _failure_run(
                run_id=11,
                head_sha="e" * 40,
                progress_comment_id=909,
                created_at="2026-09-29T12:00:00Z",
            )
        ]
    )

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == "e" * 40
    assert state.round_index == 1
    assert state.progress_comment_id == 909


async def test_a_newer_failure_run_outranks_an_older_success_run(tmp_path: Path) -> None:
    newer = _failure_run(
        run_id=22,
        head_sha="2" * 40,
        progress_comment_id=222,
        created_at="2026-09-29T12:00:00Z",
    )
    older = _trusted_run(
        run_id=21,
        head_sha="1" * 40,
        progress_comment_id=111,
        created_at="2026-09-29T09:00:00Z",
    )

    state = await _recover(_scm_with_runs([newer, older]), tmp_path)

    assert state.reviewed_head_sha == "2" * 40
    assert state.round_index == 2
    assert state.progress_comment_id == 222


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "timed_out", "neutral", None])
async def test_runs_that_did_not_complete_a_review_are_ignored(
    tmp_path: Path, conclusion: str | None
) -> None:
    run = _run(31, created_at="2026-09-29T12:00:00Z")
    run["conclusion"] = conclusion
    if conclusion is None:
        run["status"] = "in_progress"
    scm = _ActionsScm(
        runs=[run],
        artifacts={31: [_artifact(artifact_id=310)]},
        zips={310: _packet_zip(reviewed_head_sha="9" * 40, progress_comment_id=1)},
    )

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None


async def test_a_failure_run_from_another_event_or_pr_is_still_ignored(tmp_path: Path) -> None:
    other_event = _run(41, event="pull_request", conclusion="failure")
    other_pr = _run(42, conclusion="failure", pull_number=_PR_NUMBER + 1)
    scm = _ActionsScm(
        runs=[other_event, other_pr],
        artifacts={41: [_artifact(artifact_id=410)], 42: [_artifact(artifact_id=420)]},
        zips={
            410: _packet_zip(reviewed_head_sha="4" * 40, progress_comment_id=1),
            420: _packet_zip(reviewed_head_sha="5" * 40, progress_comment_id=2),
        },
    )

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0


async def test_runs_are_read_only_through_the_trusted_workflow(tmp_path: Path) -> None:
    scm = _scm_with_runs(
        [
            _failure_run(
                run_id=51,
                head_sha="6" * 40,
                progress_comment_id=None,
                created_at="2026-09-29T12:00:00Z",
            )
        ]
    )

    await _recover(scm, tmp_path)

    listings = [(path, params) for path, params in scm.requests if path.endswith("/runs")]
    assert listings
    assert all(_WORKFLOW in path or path.endswith("/mergecraft.yml/runs") for path, _ in listings)
    assert all(params.get("event") == "pull_request_target" for _, params in listings)


async def test_a_newer_failure_run_without_an_artefact_falls_back_to_the_older_run(
    tmp_path: Path,
) -> None:
    older = _trusted_run(
        run_id=61,
        head_sha="a" * 40,
        progress_comment_id=616,
        created_at="2026-09-29T09:00:00Z",
    )
    scm = _scm_with_runs(
        [older],
        extra_runs=[_run(62, conclusion="failure", created_at="2026-09-29T12:00:00Z")],
    )

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == "a" * 40
    assert state.progress_comment_id == 616
    assert state.round_index == 1, "the artefact-less run is not a round"


async def test_a_failure_run_whose_packet_names_no_head_is_not_a_checkpoint(
    tmp_path: Path,
) -> None:
    older = _trusted_run(
        run_id=71,
        head_sha="b" * 40,
        progress_comment_id=717,
        created_at="2026-09-29T09:00:00Z",
    )
    headless = (
        _run(72, conclusion="failure", created_at="2026-09-29T12:00:00Z"),
        _artifact(artifact_id=720),
        _packet_zip(reviewed_head_sha="", progress_comment_id=None),
    )

    state = await _recover(_scm_with_runs([older, headless]), tmp_path)

    assert state.reviewed_head_sha == "b" * 40
    assert state.round_index == 1


async def test_only_artefactless_failure_runs_stay_fail_closed(tmp_path: Path) -> None:
    scm = _ActionsScm(
        runs=[_run(81, conclusion="failure"), _run(82, conclusion="failure")],
        artifacts={81: [], 82: []},
    )

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None


async def test_the_search_for_a_usable_run_is_bounded_and_says_so(tmp_path: Path) -> None:
    from mergecraft.mcp.checkout import _RUN_BOUND_MAX_RUN_PROBES

    runs = [
        _run(1000 + n, conclusion="failure", created_at=f"2026-09-29T12:{59 - n:02d}:00Z")
        for n in range(_RUN_BOUND_MAX_RUN_PROBES + 2)
    ]
    scm = _ActionsScm(runs=runs, artifacts={})
    with _capture_warnings() as warnings:
        state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert warnings
    artefact_listings = [path for path, _ in scm.requests if path.endswith("/artifacts")]
    assert len(artefact_listings) == _RUN_BOUND_MAX_RUN_PROBES
