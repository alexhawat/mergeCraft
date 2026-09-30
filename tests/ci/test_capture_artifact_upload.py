"""An Action run must upload the verdict-capture file with the evidence packet.

An Action run with capture enabled writes ``judge-verdicts.jsonl`` into the
run's evidence directory. The three review rungs each upload their evidence
packet; if no upload step also names the capture file, the file is discarded
with the runner — the operator turns capture on, the run looks healthy, and the
calibration data never arrives. That is a dead control: enabled, unreachable.

This pins the upload half. The resolver half (capture and packet share one
destination policy) is pinned in the verdict-capture suite.
"""

from __future__ import annotations

from typing import Any

from tests.ci.workflow_support import load_workflow, read_text

_WORKFLOW = "mergecraft.yml"
_WORKFLOW_PATH = f".github/workflows/{_WORKFLOW}"
_CAPTURE = "judge-verdicts.jsonl"
_CAPTURE_PATH = "${{ runner.temp }}/mergecraft/judge-verdicts.jsonl"
_EVIDENCE_PREFIX = "mergecraft-evidence-"
_RUNG_NAMES = frozenset(
    {
        "mergecraft-evidence-nous",
        "mergecraft-evidence-codex",
        "mergecraft-evidence-claude",
    }
)


def _steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for job_value in (doc.get("jobs") or {}).values():
        if not isinstance(job_value, dict):
            continue
        for step in job_value.get("steps") or []:
            if isinstance(step, dict):
                steps.append(step)
    return steps


def _evidence_uploads(doc: dict[str, Any]) -> list[dict[str, Any]]:
    uploads: list[dict[str, Any]] = []
    for step in _steps(doc):
        if not str(step.get("uses") or "").startswith("actions/upload-artifact"):
            continue
        with_block = step.get("with")
        if not isinstance(with_block, dict):
            continue
        if str(with_block.get("name") or "").startswith(_EVIDENCE_PREFIX):
            uploads.append(step)
    return uploads


def test_each_review_rung_uploads_the_capture_file_alongside_its_packet() -> None:
    """Every evidence upload names both the packet and the capture file."""
    uploads = _evidence_uploads(load_workflow(_WORKFLOW))
    names = {str(step["with"]["name"]) for step in uploads}
    assert names == set(_RUNG_NAMES), (
        f"the evidence upload steps changed: {sorted(names)!r}; the three review "
        "rungs must each upload their own evidence"
    )
    for step in uploads:
        paths = str(step["with"].get("path") or "")
        assert _CAPTURE in paths, (
            f"{step['with']['name']} does not upload {_CAPTURE}: a run with capture "
            "on would discard the file with the runner and the control would be dead"
        )
        assert "packet-" in paths, (
            f"{step['with']['name']} no longer uploads its evidence packet: {paths!r}"
        )


def test_the_uploaded_capture_path_matches_the_action_destination() -> None:
    """The named path must be the resolver's Action destination, not a tmpdir."""
    text = read_text(_WORKFLOW_PATH)
    assert _CAPTURE_PATH in text, (
        "the workflow no longer names the capture file at the resolver's Action "
        "destination ($RUNNER_TEMP/mergecraft); the upload would not find it"
    )
