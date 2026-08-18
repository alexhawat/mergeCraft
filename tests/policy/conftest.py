"""Shared fixtures for the DG5 policy-as-code RED suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

VALID_RULE_YAML = """
id: no-hardcoded-secrets
owner: platform-security
version: 1
rationale: Secrets in source are a credential leak risk.
severity: Major
enforcement: blocking
scope:
  path: "**/*.py"
"""

MALFORMED_RULE_YAML = """
id: missing-required-fields
enforcement: advisory
"""

UNKNOWN_KEY_RULE_YAML = """
id: extra-field
owner: platform
version: 1
rationale: Unknown keys must fail closed.
severity: Minor
enforcement: advisory
unexpected_key: not-allowed
"""

ORG_RULE_YAML = """
id: org-baseline
owner: org-platform
version: 1
rationale: Org-wide baseline.
severity: Minor
enforcement: advisory
scope:
  org: acme-corp
"""

REPO_RULE_YAML = """
id: repo-override
owner: team-alpha
version: 1
rationale: Repo-specific stricter rule.
severity: Major
enforcement: required
scope:
  org: acme-corp
  repo: payments-api
"""

PATH_RULE_YAML = """
id: path-specific
owner: team-alpha
version: 1
rationale: Path-scoped blocking rule.
severity: Critical
enforcement: blocking
scope:
  org: acme-corp
  repo: payments-api
  path: "src/handlers/**"
"""

ACTIVE_EXCEPTION_YAML = """
id: temp-waiver
rule_id: no-hardcoded-secrets
reason: emergency hotfix with tracked follow-up
approver: security-lead
scope:
  path: "src/legacy/**"
expires_at: "2099-12-31T23:59:59Z"
"""

EXPIRED_EXCEPTION_YAML = """
id: stale-waiver
rule_id: no-hardcoded-secrets
reason: expired waiver
approver: security-lead
scope:
  path: "src/legacy/**"
expires_at: "2020-01-01T00:00:00Z"
"""

POLICY_LINT_FIXTURES = """
rules:
  - id: should-trigger
    owner: platform
    version: 1
    rationale: Matches fixture violation.
    severity: Major
    enforcement: blocking
    scope:
      path: "src/app.py"
  - id: should-not-trigger
    owner: platform
    version: 1
    rationale: Does not match fixture diff.
    severity: Major
    enforcement: blocking
    scope:
      path: "docs/**"
"""


@pytest.fixture
def policy_dir(tmp_path: Path) -> Path:
    """Write a minimal policy tree under ``.mergecraft/policy/``."""
    from tests.orchestrator.conftest import write_repo_config

    write_repo_config(tmp_path)
    directory = tmp_path / ".mergecraft" / "policy"
    directory.mkdir(parents=True)
    return directory
