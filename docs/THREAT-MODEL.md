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

## Git MCP containment (plan 13 W2)

The reviewer `git` tool refuses bypass paths that previously exfiltrated
credential material or operated outside the checkout:

| Control | What it blocks | Test surface |
|---------|----------------|--------------|
| `--no-index` | Diffs outside any repository — positional confinement cannot apply | `tests/security/` + `tests/mcp/test_reviewer_resilience_git_containment.py` |
| Positional path confinement | Operands resolving outside workspace roots | Same |
| Credential deny-list | `.git/config`, `.git/credentials`, askpass tree — regardless of confinement | Same |
| `config` write flags | Any mutating `git config` on the reviewer surface | `tests/mcp/test_reviewer_resilience_ergonomics.py` |
| Credential `config --get` keys | `credential.*`, `url.*` lookups | Same |
| Redacted failure text | Raw stderr/stdout in tool errors passes `redact_secrets` | `mcp/git.py` |

Ergonomics (W3) added `show-ref`, `for-each-ref`, `ls-remote`, and read-only
`config` lookups so agents do not reach for `--no-index` on `.git/config`.

## Operator trust knob (plan 13 W9)

<span id="operator-trust-knob"></span>

The `trust.selfReview` knob adjusts **execution trust** for same-repo
`pull_request_target` runs. It does **not** silently grant approval authority:

- **Default `off`** — byte-identical to pre-knob behaviour; `derive_trust_tier()`
  still returns untrusted for `pull_request_target` on the authority axis.
- **`analyzers`** — trusted-tier analyzers only; authority trust stays untrusted;
  real GitHub APPROVE still flows through `mergecraft-approve.yml`.
- **`full`** — explicit operator opt-out of D14/#200 separation; requires CLI
  confirmation and run-start warning; documented as exceptional.
- **Fork PRs** — both axes stay untrusted at every level.
- **Base snapshot (D15)** — policy is read from the default-branch config snapshot
  at run start; a PR-head edit to `.mergecraft/config.yaml` cannot raise its own
  tier during that run.

Read more: [`docs/trust-policy.md`](trust-policy.md).

## Executable tests

Security invariants for this threat model run on every PR via
`tests/security/test_cd_egress.py` (plus the existing `tests/security/`
containment, clone-hardening, credential, and trust-ordering suites).
