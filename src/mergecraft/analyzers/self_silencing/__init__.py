"""Self-silencing analyzer — make a PR's own reduction of scrutiny visible (#942).

Deterministic, in-process, needs no shell and is eligible on every trust tier (like
``agentsec`` / ``antislop``). It reports two things, both from the diff alone:

* **Suppression markers** added on changed lines (``# nosec``, ``# noqa``,
  ``// eslint-disable-next-line`` …) with the rule codes they silence;
* **Config loosening** — an analyzer disabled, a rule added to ``ignore``, a path
  excluded, a rule turned off, a budget lowered — in ``.mergecraft/config.yaml``,
  ``ruff.toml`` / ``pyproject.toml``, ESLint config and security-scanner ignore files.

The suppression stays allowed; this only makes it visible ("justify in the PR or
remove"). A PR's own ``analyzers.*`` config is additionally never *applied* to its own
review (see :mod:`mergecraft.analyzers.settings_pin`).

Module: mergecraft.analyzers.self_silencing
Depends: mergecraft.analyzers.self_silencing.{markers,config_diff}, mergecraft.analyzers.finding

Exports:
    Classes:
        SelfSilencingScanResult — Findings, or a named skip.
    Functions:
        scan_diff — Scan a unified diff for added suppressions and loosened config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.self_silencing.config_diff import ConfigChange, scan_config_changes
from mergecraft.analyzers.self_silencing.markers import MarkerHit, scan_added_markers

if TYPE_CHECKING:
    from pathlib import Path

_TOOL = "self-silencing"
_TAIL = "justify in the PR or remove."
_BUMP = {"Trivial": "Minor", "Minor": "Major", "Major": "Critical", "Critical": "Critical"}


@dataclass(frozen=True, slots=True)
class SelfSilencingScanResult:
    """Outcome of scanning a diff for self-silencing changes."""

    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None


def _severity(*, major: bool, tier: Literal["trusted", "untrusted"]) -> str:
    base = "Major" if major else "Minor"
    return _BUMP[base] if tier == "untrusted" else base


def _marker_finding(hit: MarkerHit, tier: Literal["trusted", "untrusted"]) -> Finding:
    silenced = ", ".join(hit.codes) if hit.codes else "every rule on this line"
    return make_finding(
        tool=_TOOL,
        rule_id=f"suppression/{hit.marker}",
        category="Security & Privacy" if hit.security else "Maintainability & Code Quality",
        severity=_severity(major=hit.security, tier=tier),
        confidence="certain",
        message=(f"Added `{hit.marker}` suppression silencing {silenced}; {_TAIL}"),
        path=hit.path,
        start_line=hit.line,
        end_line=hit.line,
        source="analyzer",
        evidence=[hit.text[:200]],
        remediation="Justify the suppression in the PR description, or remove it.",
        introduced_by_pr="true",
    )


def _config_finding(change: ConfigChange, tier: Literal["trusted", "untrusted"]) -> Finding:
    return make_finding(
        tool=_TOOL,
        rule_id="config-loosened",
        category="Security & Privacy",
        severity=_severity(major=change.security or change.mergecraft, tier=tier),
        confidence="likely",
        message=(
            f"This PR loosens analyzer configuration in `{change.path}`: {change.description}. "
            f"A PR's own analyzer config is not applied to its own review; {_TAIL}"
        ),
        path=change.path,
        start_line=change.line,
        end_line=change.line,
        source="analyzer",
        remediation=(
            "Land analyzer or linter configuration changes in their own PR, with the reason "
            "stated; they apply from the next PR on."
        ),
        introduced_by_pr="true",
    )


def scan_diff(
    *,
    repo_root: Path,
    diff_text: str,
    tier: Literal["trusted", "untrusted"],
) -> SelfSilencingScanResult:
    """Scan ``diff_text`` for added suppressions and loosened analyzer/linter config.

    Severity: ``Major`` for a loosening edit to mergeCraft or security-scanner config and
    for an added suppression on a security rule; ``Minor`` otherwise; one level higher on
    the ``untrusted`` tier. An empty diff is a named skip, never a clean pass.
    """
    if not diff_text.strip():
        return SelfSilencingScanResult(
            findings=[],
            skipped=True,
            skip_reason="skipped self-silencing: no diff text available to scan",
        )
    findings = [_marker_finding(hit, tier) for hit in scan_added_markers(diff_text)]
    findings.extend(
        _config_finding(change, tier)
        for change in scan_config_changes(repo_root=repo_root, diff_text=diff_text)
    )
    return SelfSilencingScanResult(findings=findings)


__all__ = ["SelfSilencingScanResult", "scan_diff"]
