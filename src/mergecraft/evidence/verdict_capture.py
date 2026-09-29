"""Opt-in capture of every saved verifier verdict for judge calibration (HS2).

A saved verifier verdict used to become only a loguru line and a span, so it
could not be reconstructed into a calibration case without hand transcription —
and the ``drop`` class could not be reconstructed at all, because a dropped
finding never publishes. When capture is on, every verdict — ``confirm``,
``downgrade`` **and** ``drop`` — is appended to ``<evidence_dir>/judge-verdicts.jsonl``
in the machine-written half of :class:`~mergecraft.evals.judge_calibration.JudgeCalibrationCase`
shape (everything except the human adjudication fields).

Capture is **off by default** so ordinary reviews write nothing new. It is
enabled by one operator-controlled flag: ``--capture-verdicts`` on the offline
review path, or ``MERGECRAFT_CAPTURE_VERDICTS=1`` for Action runs, read once at
run start and snapshotted on ``ToolState.capture_verdicts``.

Every line is passed through the repository's secret-redaction boundary
(:func:`mergecraft.analyzers.redact.redact_secrets`) before it is written, so a
secret in a finding body never reaches the artefact. Writing is total and
non-throwing: a capture failure degrades to a missing line, never a failed
review.

Exports:
    CAPTURE_ENV: The enabling environment variable.
    CAPTURE_FILENAME: The per-run JSONL basename.
    build_calibration_record: Assemble the machine-written calibration half.
    capture_verdict_record: Append one redacted line.
    capture_verdicts_enabled: Whether capture is on for this run.
    resolve_capture_dir: The run's evidence directory.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets

if TYPE_CHECKING:
    from mergecraft.agents.verifier import AgentFinding, JudgeVerdict
    from mergecraft.evidence.packet import DeterministicCheck

CAPTURE_ENV = "MERGECRAFT_CAPTURE_VERDICTS"
"""Set to ``1`` to enable verdict capture for an Action run."""

CAPTURE_FILENAME = "judge-verdicts.jsonl"
"""One JSON line per saved verdict, under the run's evidence directory."""

_EVIDENCE_DIR_ENV = "MERGECRAFT_EVIDENCE_DIR"


def capture_verdicts_enabled(tool_state: Any | None = None) -> bool:
    """Return whether verdict capture is on for this run.

    The run-start snapshot on ``ToolState`` wins when it is set; the environment
    is the fallback for callers that build a context without going through the
    run entrypoint. Either way the value is operator-controlled, never read from
    a PR or an agent.
    """
    if tool_state is not None and bool(getattr(tool_state, "capture_verdicts", False)):
        return True
    return os.environ.get(CAPTURE_ENV, "").strip() == "1"


def resolve_capture_dir(*, tmpdir: str) -> Path:
    """Return the run's evidence directory.

    ``MERGECRAFT_EVIDENCE_DIR`` is the operator override; otherwise the file
    lands beside the offline run's evidence under ``<tmpdir>/evidence``. In an
    Action run ``tmpdir`` is already inside the runner-owned ``$RUNNER_TEMP``, so
    the JSONL stays outside the PR checkout and survives the step.
    """
    override = os.environ.get(_EVIDENCE_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return Path(tmpdir) / "evidence"


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def build_calibration_record(
    *,
    verdict: JudgeVerdict,
    finding: AgentFinding,
    deterministic_checks: list[DeterministicCheck],
    lane: str,
) -> dict[str, Any]:
    """Assemble the machine-written half of a ``JudgeCalibrationCase``.

    Everything a calibration case needs except the human reference and
    adjudication: the frozen finding, its deterministic checks, the lane, the
    evidence digest, the saved pinned verdict, and the prompt/policy contract.
    The keys are a strict subset of ``JudgeCalibrationCase.model_fields``, so a
    reader can complete the human half and validate the whole record.
    """
    from mergecraft.agents.verifier import (
        VERIFIER_JUDGE_POLICY_ID,
        verifier_policy_parameters,
        verifier_prompt_sha256,
    )

    checks = [check.model_dump(mode="json") for check in deterministic_checks]
    finding_payload = finding.model_dump(mode="json")
    evidence_payload = json.dumps(
        {
            "finding": finding_payload,
            "deterministic_checks": checks,
            "lane": lane,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "case_id": verdict.fingerprint,
        "finding": finding_payload,
        "deterministic_checks": checks,
        "lane": lane,
        "evidence_sha256": _digest(evidence_payload),
        "saved_judge_verdict": verdict.model_dump(mode="json"),
        "prompt_sha256": verifier_prompt_sha256(),
        "policy_id": VERIFIER_JUDGE_POLICY_ID,
        "policy_parameters": verifier_policy_parameters(),
    }


def capture_verdict_record(
    *,
    evidence_dir: Path,
    verdict: JudgeVerdict,
    finding: AgentFinding,
    deterministic_checks: list[DeterministicCheck],
    lane: str,
) -> Path | None:
    """Append one redacted calibration line; never raise into the run.

    Returns the JSONL path on success, or ``None`` when the write degraded. The
    line is redacted as a whole, so a secret anywhere in the finding or reason
    cannot reach the artefact.
    """
    try:
        record = build_calibration_record(
            verdict=verdict,
            finding=finding,
            deterministic_checks=deterministic_checks,
            lane=lane,
        )
        line = redact_secrets(json.dumps(record, ensure_ascii=False, sort_keys=True))
        path = Path(evidence_dir) / CAPTURE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
        return path
    except Exception as err:  # a capture artefact never fails a review
        logger.warning("judge-verdict capture failed: {}", err)
        return None


__all__ = [
    "CAPTURE_ENV",
    "CAPTURE_FILENAME",
    "build_calibration_record",
    "capture_verdict_record",
    "capture_verdicts_enabled",
    "resolve_capture_dir",
]
