# Threat model — enforced controls, network boundary, SSRF, and scans

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

## What is enforced, and where

Each control below names the function that enforces it and a test that fails if
the control stops holding. A name that appears here without a caller in the
product is not a control.

| Control | Enforced by | Test |
|---------|-------------|------|
| SSRF guard on external retrieval (loopback, link-local, metadata, `file:`, odd IP forms; unresolvable names fail closed) | `mergecraft.security.egress:guard_external_url`, `mergecraft.security.egress:inspect_external_url` | `tests/security/test_cd_egress.py::test_ssrf_protections_block_link_local_and_metadata_urls` |
| Analyzer downloads connect only to the addresses the SSRF check validated | `mergecraft.security.egress:pinned_http_transport` (used by `analyzers/provision.py`) | `tests/security/test_egress_pinned_failover.py::test_first_address_unreachable_falls_over_to_the_second` |
| Analyzer network isolation: an untrusted-tier analyzer that declares a network allowlist runs only when a filtered-egress backend can be set up; otherwise it does not run (a named skip, or an `unavailable` row) | `mergecraft.analyzers.sandbox:analyzer_egress_skip_reason`, `mergecraft.analyzers.sandbox:build_analyzer_sandbox_argv_for_run` | `tests/analyzers/test_analyzer_egress_policy.py` |
| Secrets are redacted from analyzer output before it becomes a finding | `mergecraft.analyzers.redact:redact_analyzer_output` (called from `analyzers/run.py`) | `tests/analyzers/test_redact_entropy.py` |
| Findings are redacted again before SARIF upload | `mergecraft.analyzers.sarif_upload:redact_findings_for_upload` | `tests/analyzers/test_sarif_upload.py` |

## Network egress

mergeCraft does not filter outbound traffic from the review agent: the agent
process uses the runner's network, and a compromised agent can still reach the
internet ([SECURITY.md](../SECURITY.md)). Egress is constrained in two places
only: analyzer subprocesses (the analyzer row above; see
[`docs/ANALYZERS.md`](ANALYZERS.md) for the backends and their limits) and
mergeCraft's own external retrieval (the SSRF rows above).

`mergecraft.security.egress.allow_egress` and its default host list exist as a
helper, but no product code path calls it; it is not an enforced control.

## SSRF on external retrieval

`guard_external_url` refuses loopback, IPv6 localhost, link-local / cloud
metadata (`169.254.169.254`), and `file:` URLs before any fetch. Callers:
`utils/source_resolve.py`, `mcp/upload.py`, and `analyzers/provision.py` (which
then pins the connection to the validated addresses). Tests live in
`tests/security/test_cd_egress.py` (`test_ssrf_protections_block_link_local_and_metadata_urls`).

## Vulnerability scanning

`dependency_vulnerability_gate` and `container_image_vulnerability_gate` in
`mergecraft.security.egress` return a fixed "not run" report. They are named
placeholders, not gates, and nothing in the product calls them. The scans that
run are:

| Scan | Where |
|------|-------|
| Bandit (medium and above) and `pip-audit` against OSV | `make security`, run by the `security` job in `.github/workflows/ci.yml` |
| SBOM and Trivy HIGH/CRITICAL on built images | the `sbom-scan` job in `.github/workflows/ci-cd.yml` and `.github/workflows/image-security.yml` — see [`docs/supply-chain.md`](supply-chain.md) |

## Public comments

`mergecraft.analyzers.redact.redact_secrets` is applied at specific seams: analyzer
output and findings (`analyzers/run.py`, `analyzers/parse.py`), SARIF upload,
trace events, and reviewer `git` tool errors (`mcp/git.py`). Publication is not
centralized behind one redaction call, so the table above lists only the seams
that are tested. `test_public_comments_never_include_secret_material` in
`tests/security/test_cd_egress.py` exercises the redactor itself, not a
publication path.

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
- **`full`** — explicit operator opt-out of the authority/execution
  separation from PR #200; requires CLI confirmation and run-start warning;
  documented as exceptional.
- **Fork PRs** — both axes stay untrusted at every level.
- **Base snapshot** — policy is read from the default-branch config snapshot
  at run start; a PR-head edit to `.mergecraft/config.yaml` cannot raise its own
  tier during that run.

Read more: [`docs/trust-policy.md`](trust-policy.md).

## Executable tests

Security invariants for this threat model run on every PR via
`tests/security/test_cd_egress.py` (plus the existing `tests/security/`
containment, clone-hardening, credential, and trust-ordering suites).
