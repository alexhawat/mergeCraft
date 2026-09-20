"""Render the Jev summary section for a review body (#786).

Jev's questions and answers were computed, logged, and discarded — this module
is the only place that turns them into the section a human reads. It is a
pure leaf: no I/O, no client, no settings resolution. Callers pass in exactly
what happened (enabled, a skip reason, or predictions) and get back Markdown
or ``None``.

Two properties are load-bearing and covered by tests, not just docstrings:

* With Jev disabled, this returns ``None`` — the caller must not render an
  empty section or a "disabled" line, so the review body stays byte-identical
  to a run with no Jev at all.
* Every rendered section states that Jev is advisory and names its pinned
  model, so a confident-looking confidence score is never mistaken for a
  verdict (`predict_jev_action` returns ``enforced=False`` unconditionally —
  see ``docs/jev-gate-patterns.md``'s enforcement-status section).

Exports:
    JEV_SKIP_REASON_LABELS: Human labels for the ``JevSkipReason`` tokens.
    render_jev_review_section: Build the collapsed Markdown section, or None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

JEV_SKIP_REASON_LABELS: dict[str, str] = {
    "disabled": "Jev was enabled but a required pack was disabled",
    "credential_absent": "the `TYPESAFE_API_KEY` credential was not available",
    "kill_switch": "the token budget kill switch was active",
}

_ADVISORY_NOTE = (
    "Advisory only. Jev ranks and annotates candidate units; it never skips the "
    "reviewer, suppresses a finding, or blocks a merge — `enforced` is always "
    "`false`. Thresholds are unmeasured starting points, not calibrated values "
    "(see `docs/jev-gate-patterns.md`)."
)


def _prediction_row(prediction: Mapping[str, Any]) -> str:
    unit_id = str(prediction.get("unit_id") or "unknown-unit")
    lane = prediction.get("lane") or "—"
    choice = prediction.get("choice") or "—"
    severity = prediction.get("severity") or "—"
    confidence = prediction.get("confidence")
    confidence_display = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "—"
    return f"| `{unit_id}` | {lane} | {choice} | {severity} | {confidence_display:>10} |"


def render_jev_review_section(
    *,
    enabled: bool,
    skip_reason: str | None,
    predictions: Sequence[Mapping[str, Any]] | None,
    model: str,
) -> str | None:
    """Render the collapsed Jev summary section, or ``None`` when it must be absent.

    Args:
        enabled: ``settings.jev.enabled`` for this run. ``False`` always
            returns ``None`` — no empty section, no "disabled" line (#786).
        skip_reason: ``OfflineReviewResult.jev_skip_reason`` — one of
            ``disabled`` / ``credential_absent`` / ``kill_switch`` when Jev
            was enabled but did not run, else ``None``.
        predictions: Per-unit ``JevPrediction`` dumps from
            ``dispatch_residual_units``, when Jev ran to completion.
        model: The pinned Jev model id, for the section footer.

    Returns:
        str | None: Markdown ``<details>`` block, or ``None`` when Jev is
        disabled for this run.
    """
    if not enabled:
        return None

    if skip_reason:
        label = JEV_SKIP_REASON_LABELS.get(skip_reason, skip_reason)
        lines = [
            "<details>",
            "<summary>Jev screening — enabled, did not run</summary>",
            "",
            f"Jev is enabled but this run recorded a skip: `{skip_reason}` — {label}.",
            "",
            _ADVISORY_NOTE,
            "",
            "</details>",
        ]
        return "\n".join(lines)

    rows = list(predictions or [])
    flagged = [row for row in rows if str(row.get("choice", "")).lower() not in {"", "clean"}]
    summary = f"Jev screening — {len(rows)} units, {len(flagged)} flagged (shadow, advisory)"

    lines = ["<details>", f"<summary>{summary}</summary>", ""]
    if rows:
        lines.extend(
            [
                "| Unit | Lane | Choice | Severity | Confidence |",
                "|------|------|--------|----------|-----------:|",
            ]
        )
        lines.extend(_prediction_row(row) for row in rows)
        lines.append("")
    else:
        lines.append("_No residual units were screened this run._")
        lines.append("")
    lines.append(f"Model `{model}`.")
    lines.append("")
    lines.append(_ADVISORY_NOTE)
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


__all__ = ["JEV_SKIP_REASON_LABELS", "render_jev_review_section"]
