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
    return [str(item.get("conclusion", "")).strip().lower() for item in attempts]


def _base_outcome(run: dict[str, Any]) -> str:
    """Normalise a base-run conclusion the same way retry attempts are (BL-D3/BL-D6)."""
    return str(run.get("conclusion", "")).strip().lower() or "unknown"


def newest_base_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest row per base workflow and branch; rows arrive newest-first.

    The producer (``ci/base_runs.py``) lists each workflow's runs newest-first
    with refs shaped ``<branch>@<sha>``, so the first row seen for a
    (workflow, branch) pair is its latest verdict. Older rows of the same pair
    stay evidence, never the verdict (#1321).
    """
    newest: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        branch = str(run.get("ref") or "").split("@", 1)[0]
        newest.setdefault((str(run.get("workflow") or ""), branch), run)
    return list(newest.values())


def classify_failure(
    *,
    fingerprint: str,
    attempts: list[dict[str, Any]],
    base_branch_runs: list[dict[str, Any]],
) -> FlakyVerdict:
    """Classify retry/base-branch behaviour for one failure fingerprint.

    ``pre_existing`` requires the newest matching base run of a workflow to have
    concluded ``failure`` (BL-D6); an older same-fingerprint failure behind a newer
    pass is evidence only. A matching base run that *passed* when this PR's
    attempts failed is evidence the failure is new here: ``stable`` with
    ``blame_on_author=True``.
    """
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
        evidence.append(f"{ref} saw fingerprint {fingerprint} as {_base_outcome(run)}")

    deciding_base = newest_base_runs(matching_base)
    failing_base = [run for run in deciding_base if _base_outcome(run) == "failure"]
    if failing_base:
        ref = str(failing_base[0].get("ref", "base branch"))
        return FlakyVerdict(
            classification="pre_existing",
            summary=(
                f"Base branch {ref} failed with this fingerprint; "
                "treat as pre-existing rather than introduced by this PR."
            ),
            evidence=evidence,
            blame_on_author=False,
        )

    if has_failure:
        passing_base = [run for run in deciding_base if _base_outcome(run) == "success"]
        if passing_base:
            refs = ", ".join(str(run.get("ref", "base branch")) for run in passing_base)
            return FlakyVerdict(
                classification="stable",
                summary=(
                    f"Base branch {refs} passed with this fingerprint; "
                    "the failure is not explained by the base branch."
                ),
                evidence=evidence,
                blame_on_author=True,
            )

    if matching_base:
        described = ", ".join(
            f"{run.get('ref', 'base branch')!s} concluded {_base_outcome(run)}"
            for run in matching_base
        )
        summary = f"Base-branch evidence does not explain this failure ({described})."
    else:
        summary = "No retry flip or base-branch match for this fingerprint."

    return FlakyVerdict(
        classification="stable",
        summary=summary,
        evidence=evidence,
        blame_on_author=has_failure,
    )


__all__ = ["FlakyClassification", "FlakyVerdict", "classify_failure", "newest_base_runs"]
