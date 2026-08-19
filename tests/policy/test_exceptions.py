"""DG5 policy exceptions — bounded waivers with expiry (G11).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — exceptions require reason, approver, scope, expiry.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.policy.conftest import ACTIVE_EXCEPTION_YAML, EXPIRED_EXCEPTION_YAML


def test_exception_requires_reason_approver_scope_and_expiry() -> None:
    """Waivers must carry reason, approver, scope, and an expiry timestamp."""
    from mergecraft.policy.exceptions import PolicyConfigError, parse_exception

    exc = parse_exception(ACTIVE_EXCEPTION_YAML)

    assert exc.reason == "emergency hotfix with tracked follow-up"
    assert exc.approver == "security-lead"
    assert exc.scope.path == "src/legacy/**"
    assert exc.expires_at.year == 2099

    incomplete = """
id: incomplete-waiver
rule_id: no-hardcoded-secrets
"""
    with pytest.raises(PolicyConfigError, match=r"reason|approver|scope|expiry|expires"):
        parse_exception(incomplete)


def test_exception_validation_errors_mention_policy_exception() -> None:
    """Exception schema failures must not reuse policy-rule wording."""
    from mergecraft.policy.exceptions import PolicyConfigError, parse_exception

    incomplete = """
id: incomplete-waiver
rule_id: no-hardcoded-secrets
"""
    with pytest.raises(PolicyConfigError, match=r"policy exception"):
        parse_exception(incomplete)


def test_expired_exception_stops_applying() -> None:
    """An expired waiver no longer suppresses its scoped rule."""
    from mergecraft.policy.exceptions import exception_applies, parse_exception
    from mergecraft.policy.scoping import ScopeContext

    expired = parse_exception(EXPIRED_EXCEPTION_YAML)
    context = ScopeContext(
        org="acme-corp",
        repo="payments-api",
        branch="main",
        path="src/legacy/old.py",
        language="python",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert exception_applies(expired, context=context, now=now) is False
