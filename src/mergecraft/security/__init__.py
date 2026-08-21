"""Network-boundary and publication security surfaces (#362).

Exports:
    DEFAULT_EGRESS_ALLOWLIST: Hosts allowed when deployment applies egress.
    VulnerabilityGateReport: Named dependency or image scan outcome.
    allow_egress: Host allow-list check.
    container_image_vulnerability_gate: Image scan distinct from make security.
    dependency_vulnerability_gate: Dependency advisory gate.
    guard_external_url: SSRF refusal for untrusted retrieval URLs.
    redact_secrets_for_public_comment: Strip secret material before publish.
"""

from __future__ import annotations

from mergecraft.security.egress import (
    DEFAULT_EGRESS_ALLOWLIST,
    VulnerabilityGateReport,
    allow_egress,
    container_image_vulnerability_gate,
    dependency_vulnerability_gate,
    guard_external_url,
)
from mergecraft.security.public_comments import redact_secrets_for_public_comment

__all__ = [
    "DEFAULT_EGRESS_ALLOWLIST",
    "VulnerabilityGateReport",
    "allow_egress",
    "container_image_vulnerability_gate",
    "dependency_vulnerability_gate",
    "guard_external_url",
    "redact_secrets_for_public_comment",
]
