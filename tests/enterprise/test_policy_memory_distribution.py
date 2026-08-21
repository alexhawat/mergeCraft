"""W7.1 — org policy and memory distribution without a dashboard (#381, D6).

Wraps existing ``mergecraft.policy`` / ``mergecraft.memory`` — does not re-author them.
Intended public API (W7.2): ``mergecraft.enterprise.policy_distribution`` and
``mergecraft.enterprise.memory_distribution``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.memory import LocalMemoryBackend
from mergecraft.policy import parse_rules_document

_MINIMAL_RULES = """
rules:
  - id: testing.behavior-coverage-for-src
    owner: mergecraft-quality
    version: 1
    rationale: Source changes need a matching should-fail-then-pass test.
    severity: Minor
    enforcement: advisory
    scope:
      path: "src/**"
"""


def test_distribute_org_policy_from_files_without_dashboard(tmp_path: Path) -> None:
    """Happy: file-backed policy distribution does not require a dashboard URL."""
    from mergecraft.enterprise.policy_distribution import distribute_org_policy

    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(_MINIMAL_RULES, encoding="utf-8")
    result = distribute_org_policy(rules_path, dashboard_url=None)
    assert result is not None
    assert parse_rules_document(_MINIMAL_RULES)


def test_distribute_org_policy_rejects_dashboard_only_source() -> None:
    """Error: a dashboard-only source is refused (no dashboard required)."""
    from mergecraft.enterprise.policy_distribution import distribute_org_policy

    with pytest.raises((ValueError, RuntimeError), match="dashboard"):
        distribute_org_policy(None, dashboard_url="https://dashboard.example/org")


def test_bind_org_memory_uses_existing_backend() -> None:
    """Happy: org memory binds to 20c's OrganizationMemoryBackend without a dashboard."""
    from mergecraft.enterprise.memory_distribution import bind_org_memory

    backend = LocalMemoryBackend()
    bound = bind_org_memory(backend, dashboard_url=None)
    bound.put("policy-pack", "shipped")
    assert bound.get("policy-pack") == "shipped"
    assert "policy-pack" in bound.list()


def test_bind_org_memory_rejects_dashboard_url() -> None:
    """Error: passing a dashboard URL is refused — distribution is file/API only."""
    from mergecraft.enterprise.memory_distribution import bind_org_memory

    with pytest.raises((ValueError, RuntimeError), match="dashboard"):
        bind_org_memory(LocalMemoryBackend(), dashboard_url="https://dashboard.example/org")
