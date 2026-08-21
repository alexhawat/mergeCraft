# Threat model — network boundary, SSRF, and vulnerability gates

This document binds the #362 security residue to executable tests. It is not
an independent security review.

## Independent security review

Commission an **independent security review** before the first stable
production release. The checks below are the in-tree regression surface; they
do not replace that review.

## Assets

- Reviewer credentials and BYOK provider keys in the Action environment
- Untrusted PR trees, tickets, and linked-repo content
- Public GitHub review comments and check-run output
- Published container images (`ghcr.io/alexhawat/mergecraft`)

## Network egress

Deployments that can filter outbound traffic apply
`mergecraft.security.egress.allow_egress`. Unlisted hosts are denied. The
default allow-list is GitHub API and registry hosts needed to clone and
publish; `evil.example` and similar arbitrary hosts are refused.

## SSRF on external retrieval

`guard_external_url` refuses loopback, IPv6 localhost, link-local / cloud
metadata (`169.254.169.254`), and `file:` URLs before any fetch. Tests live in
`tests/security/test_cd_egress.py` (`test_ssrf_protections_block_link_local_and_metadata_urls`).

## Vulnerability gates

| Gate | Callable | Distinct from |
|------|----------|----------------|
| Dependencies | `dependency_vulnerability_gate` | — (pip-audit / OSV; `make security` already runs this for the Python tree) |
| Container image | `container_image_vulnerability_gate` | **`make security`** (Bandit + pip-audit). Image scanning is Trivy HIGH/CRITICAL on published digests — see `docs/supply-chain.md`. |

## Public comments

`redact_secrets_for_public_comment` strips secret-shaped tokens before a
body is posted. Public comments must never include provider keys or similar
material.

## Executable tests

Security invariants for this threat model run on every PR via
`tests/security/test_cd_egress.py` (plus the existing `tests/security/`
containment, clone-hardening, credential, and trust-ordering suites).
