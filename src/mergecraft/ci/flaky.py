"""Flaky and pre-existing failure classification (K2 / K4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FlakyClassification = Literal["flaky", "pre_existing", "stable"]


@dataclass(frozen=True)
class FlakyVerdict:
    classification: FlakyClassification
    summary: str
    evidence: list[str] = field(default_factory=list)
    blame_on_author: bool = True


def _attempt_outcomes(attempts: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("conclusion", "")).lower() for item in attempts]


def classify_failure(
    *,
    fingerprint: str,
    attempts: list[dict[str, Any]],
    base_branch_runs: list[dict[str, Any]],
) -> FlakyVerdict:
    """Classify retry/base-branch behaviour for one failure fingerprint."""
    evidence: list[str] = []
    outcomes = _attempt_outcomes(attempts)
    has_failure = any(outcome == "failure" for outcome in outcomes)
    has_success = any(outcome == "success" for outcome in outcomes)

    if has_failure and has_success:
        evidence.append(f"fingerprint {fingerprint}: retry outcomes mixed ({', '.join(outcomes)})")
        return FlakyVerdict(
            classification="flaky",
            summary="This failure looks flaky — the same fingerprint passed on retry.",
            evidence=evidence,
            blame_on_author=False,
        )

    matching_base = [
        run
        for run in base_branch_runs
        if run.get("fingerprint") == fingerprint or str(run.get("fingerprint", "")) == fingerprint
    ]
    for run in matching_base:
        ref = str(run.get("ref", "base branch"))
        conclusion = str(run.get("conclusion", "unknown"))
        evidence.append(f"{ref} saw fingerprint {fingerprint} as {conclusion}")

    if matching_base and has_failure:
        ref = str(matching_base[0].get("ref", "base branch"))
        return FlakyVerdict(
            classification="pre_existing",
            summary=(
                f"Same failure fingerprint already fails on {ref}; "
                "treat as pre-existing rather than introduced by this PR."
            ),
            evidence=evidence,
            blame_on_author=False,
        )

    if matching_base and has_success and has_failure:
        ref = str(matching_base[0].get("ref", "pre-0.0.1"))
        evidence.append(f"{ref} also shows mixed outcomes for this fingerprint")
        return FlakyVerdict(
            classification="flaky",
            summary=f"This test is flaky on {ref} too — do not blame the PR author.",
            evidence=evidence,
            blame_on_author=False,
        )

    if matching_base:
        ref = str(matching_base[0].get("ref", "base branch"))
        conclusion = str(matching_base[0].get("conclusion", "unknown"))
        if conclusion == "failure":
            return FlakyVerdict(
                classification="pre_existing",
                summary=f"Base branch {ref} already reports this fingerprint as failing.",
                evidence=evidence,
                blame_on_author=False,
            )

    return FlakyVerdict(
        classification="stable",
        summary="No retry flip or base-branch match for this fingerprint.",
        evidence=evidence,
        blame_on_author=has_failure,
    )


__all__ = ["FlakyClassification", "FlakyVerdict", "classify_failure"]
