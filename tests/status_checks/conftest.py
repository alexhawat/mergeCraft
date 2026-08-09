"""Shared fixtures for the W7 RED suite (#75 structural approval gate).

W7 is the test-creator wave for Batch D. It pins the acceptance contract that
W8 (executor) must satisfy:

- The approval conclusion is a pure function of findings + run state + trust
  tier (D12). Narrative never enters the decision.
- A crashed / timed-out / no-findings run never leaves a permissive gate (D13).
- Untrusted (fork / ``pull_request_target``) runs cannot self-approve even
  with ``prApproveEnabled=True`` (D14).
- The agent's ``approved`` boolean is advisory only — never the sole positive
  input (D12).
- The approval path reuses ``Finding`` from ``analyzers/finding.py`` and
  defines no parallel model (D12).

Each test is decorated with ``@pytest.mark.xfail(reason="green after W8",
strict=False)`` on the test functions themselves so they collect even though
the decision function does not exist yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.review_taxonomy import FindingSource

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding


@pytest.fixture
def blocker_finding() -> Finding:
    """One Major-severity finding — the smallest input that must trip the gate."""
    return make_finding(
        tool="structural-approval-fixture",
        rule_id="W7-BLOCKER",
        category="Security & Privacy",
        severity="Major",
        confidence="certain",
        message="Fence module imported but never used.",
        path="src/mergecraft/utils/fence.py",
        start_line=1,
        end_line=10,
        source="agent",
        evidence=["fence is imported but never referenced"],
        remediation="Use the fence for every untrusted-field interpolation.",
        fingerprint="w7-blocker-mjr",
    )


@pytest.fixture
def critical_finding() -> Finding:
    """One Critical-severity finding — also blocking."""
    return make_finding(
        tool="structural-approval-fixture",
        rule_id="W7-CRITICAL",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="Approval decision reads from agent prose.",
        path="src/mergecraft/utils/status_checks.py",
        start_line=46,
        end_line=120,
        source="agent",
        evidence=["report_status_checks() branches on approval.would_approve"],
        remediation="Route through decide_approval() with typed findings.",
        fingerprint="w7-critical-cr",
    )


@pytest.fixture
def trivial_finding() -> Finding:
    """One Trivial-severity finding — never trips the gate on its own."""
    return make_finding(
        tool="structural-approval-fixture",
        rule_id="W7-NIT",
        category="Maintainability & Code Quality",
        severity="Trivial",
        confidence="possible",
        message="Docstring missing a trailing period.",
        path="src/mergecraft/utils/status_checks.py",
        start_line=1,
        end_line=1,
        source="ci",
        evidence=["line 1: ''"],
        remediation="Add a period.",
        fingerprint="w7-trivial-tr",
    )


@pytest.fixture
def sample_findings(
    blocker_finding: Finding,
    critical_finding: Finding,
    trivial_finding: Finding,
) -> list[Finding]:
    """Mixed-severity finding list — one of each kind."""
    return [critical_finding, blocker_finding, trivial_finding]


@pytest.fixture
def blocker_only_findings(blocker_finding: Finding) -> list[Finding]:
    """A focused list containing only one blocker."""
    return [blocker_finding]


@pytest.fixture
def clean_findings() -> list[Finding]:
    """An empty list — nothing to flag, but the run still has to be considered."""
    return []


@pytest.fixture
def clean_findings_with_trivial(trivial_finding: Finding) -> list[Finding]:
    """A non-empty list with only Trivial findings — must not block the gate."""
    return [trivial_finding]


@pytest.fixture
def blocked_pr_event() -> dict:
    """A fork PR event payload — what ``derive_trust_tier`` would resolve to ``untrusted``."""
    return {
        "pull_request": {
            "head": {
                "repo": {
                    "fork": True,
                    "full_name": "attacker/evil-fork",
                }
            }
        }
    }


@pytest.fixture
def trusted_pr_event() -> dict:
    """An in-repo PR event — ``derive_trust_tier`` would resolve to ``trusted``."""
    return {
        "pull_request": {
            "head": {
                "repo": {
                    "fork": False,
                    "full_name": "acme/widgets",
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# Module-availability guards — the W7 suite pins the *contract* that W8 must
# satisfy. The decision function (``decide_approval``) and trust-tier inert
# flag (``prApproveEnabled``) do not yet exist on this branch — W8 adds them.
# The fixtures above are the only "real" Finding objects; the decision helpers
# the tests call are imported lazily inside each test so an unresolved import
# is reported as a collection failure rather than a global hard fail.
# ---------------------------------------------------------------------------


def _ensure_finding_module_available() -> None:
    """``Finding`` must be importable for the suite to collect at all."""
    from mergecraft.analyzers.finding import Finding  # noqa: F401


def _ensure_status_checks_module_available() -> None:
    """`report_status_checks` and `Conclusion` must exist for the enforce tests."""
    from mergecraft.utils.status_checks import (
        Conclusion,  # noqa: F401
        report_status_checks,  # noqa: F401
    )


_ensure_finding_module_available()
_ensure_status_checks_module_available()


# Source-finding helper, used implicitly by ``FindingSource`` and made explicit
# for the structural-guard test (W7.6) so the import-coupling is asserted at
# the literal level rather than via a transitive attribute.
def _source_for_approval_path() -> FindingSource:
    """Source used by every W7 finding — keeps the suite self-consistent."""
    return "agent"
