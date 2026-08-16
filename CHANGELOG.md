# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added: server-side semantic validation of the terminal verdict — `request_changes` with no findings, `approve` over a verifier-confirmed blocker, and `approve` with a failing required deterministic check are all rejected and fail closed
- Added: `submit_review_verdict` — a typed MCP operation that records a review's terminal verdict
  (`approve` / `request_changes`), summary and structured findings. Unknown fields and invalid
  verdict values are rejected; an identical re-submission is idempotent, a conflicting one is an
  error. Not yet enforced — the run outcome is unchanged in this release
- `mergecraft tracing logfire wire-workflow` / `unwire-workflow` — surgical
  YAML mutation of `.github/workflows/*.yml` to wire (or strip) the four
  Logfire keys (`tracing: "true"`, `tracing-to: logfire`,
  `logfire-token: ${{ secrets.LOGFIRE_TOKEN }}`,
  `MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}`) on selected
  steps. Comment-preserving line-based mutator; refuses forks with
  similarly-named action names; supports both the multi-line
  (`- name: ...` / `  uses: alexhawat/mergeCraft@X`) and the inline
  (`- uses: alexhawat/mergeCraft@X`) step forms; creates a `with:` block
  when absent (README Example 1 has no `with:`); public API under
  `mergecraft.cli.tracing_logfire_wf_yaml.apply_logfire_wiring` /
  `remove_logfire_wiring` / `render_workflow_diff`
- `scripts/gen_reference_docs.py` regenerates README's `action.yml` input/output
  tables and CLI command table from the live sources (never a subprocess — it
  walks the live Typer `app` object) and splices them between HTML sentinel
  comments; `make reference-docs-check` (wired into `make ci-static`) fails the
  build on drift. Closes the audit in the issues-showcase-readiness wave plan
  (PR G2): the README table documented 9 of 24 real `action.yml` inputs and
  neither declared output anywhere

### Fixed

- Fixed: Review completion via `create_pull_request_review` now records a terminal verdict, and IncrementalReview may complete via `report_progress` without mapping to `inconclusive`
- Fixed: verifier confirms persist outside replaceable analyzer run state, including agent-authored findings
- Fixed: a verifier `confirm` now persists the finding fingerprint so `approve` over a confirmed blocker is rejected on the live tool path, not only in unit tests that seed `verified_ids`
- Fixed: a stored `approve` is re-validated at finalize against current evidence, so a later failed required gate or verifier confirm cannot leave the run `passed`
- Fixed: a provider success without a usable terminal verdict now advances the model chain when fallback is allowed, instead of accepting the first process-successful result
- Fixed: a later `run_static_checks` call that matches no gates no longer wipes a prior failed row, so `approve` still fails closed
- Fixed: `approve` is now rejected on the live path when `run_static_checks` recorded a failed required gate; previously the validator only saw those rows in unit tests
- Fixed: a review run that completes without submitting a terminal verdict now reports `inconclusive` (a `neutral` check conclusion) instead of `passed`. Previously a provider that returned successfully without reviewing anything produced a successful run. Prose such as "LGTM" has never been able to approve and still cannot
- `submit_review_verdict` now rejects non-list `findings` and severities outside
  the review taxonomy, hashes the validated payload so omitting `findings` matches
  `findings: []`, keeps a conflict flag sticky for the attempt, and scopes the
  recorded submit to the active model-chain attempt so a fallback cannot inherit
  or conflict-reject the failed attempt's verdict
- `README.md`'s CLI table documented `mergecraft traces <run-id>`, but the real
  registered command is `mergecraft traces show <run-id>` — the stale
  invocation is now generated from the live CLI app instead of hand-maintained
- `tracing_logfire_wf_yaml` `uses_re` regex now matches the inline
  `- uses: alexhawat/mergeCraft@X` step form (used by README Examples 1 and
  6) — previously the regex required leading whitespace before `uses:` and
  silently rejected every workflow the README documents. The `_do` closure
  now also synthesises a `with:` block when absent (symmetric with
  `_create_env_block`) — every `action.yml` input is `required: false`, and
  the comment claiming otherwise was wrong

### Removed

## [0.1.0] — 2026-08-14

Initial public release: mergeCraft is a standalone, BYOK GitHub Action for
AI-powered PR review — no proprietary backend, no account, review runs
against your own Claude/Codex/Gemini subscription or API key.

Full pre-release development history: see
[`docs/dev/changelog-archive.md`](docs/dev/changelog-archive.md).

### Added

- Multi-agent review drivers for Claude Code, Codex, Gemini CLI, Cursor
  Cloud, and OpenCode, each resolving from a subscription login or an API
  key with no proprietary backend in between
- Curated multi-provider catalog (Nous Research/DeepSeek, Tencent TokenHub,
  MiniMax) plus a generic custom OpenAI-compatible gateway, configurable via
  `.mergecraft/config.yaml` or `with:` inputs
- Ordered model chain with automatic fallback: entries missing credentials
  are skipped and retryable provider failures advance to the next entry
- Analyzer catalog covering linters and type-checkers (Ruff, MyPy, Pyright,
  ESLint, Biome, Oxlint), dependency and secret scanning (OSV-Scanner,
  Trivy, TruffleHog), pattern scanning (Semgrep/OpenGrep/ast-grep), contract
  diffing (oasdiff, Squawk, buf), GitHub-native tools (actionlint, zizmor,
  ShellCheck, Hadolint), and a first-party scanner for MCP/skill manifests;
  selection is trust-tier aware (`analyzers: off|auto|full|untrusted-only`)
- Merge Evidence Packet: every run emits a versioned, structured record of
  findings, analyzer checks, the blast-radius lane, and the structural
  decision, exposed as the Action's `evidence_packet` output
- Blast-radius classifier maps changed paths to low/medium/high merge
  lanes, with additive per-category repo overrides
- Structural `mergecraft-approval` status check — a pure function of typed
  findings, run completion, and trust tier, so a crashed or timed-out run
  reports `neutral` rather than silently passing
- Eight trajectory checks read the agent's own mediated tool calls (a file
  edited but never read, a tool error retried with nothing changed, and six
  more) and feed the evidence packet
- File-backed eval bank (`mergecraft eval add|list|replay|promote`) turns
  real review outcomes into regression cases and permanent pytest tests
- Optional tracing: a local JSONL sink plus Logfire/OTLP remote export, a
  full per-run span tree, and a redaction boundary that scrubs secrets
  before any sink sees them (`mergecraft tracing`, `mergecraft auth logfire`)
- `mergecraft findings export|carryover` files GitHub issues for review
  findings a merged PR left unresolved, so they survive past the merge
- Optional GitHub code-scanning upload (SARIF) for analyzer findings
  (`sarif_upload: enabled`)
- Per-run nonce fencing neutralizes prompt-injection attempts in untrusted
  PR titles, bodies, and comments before they reach the reviewing agent
- Comment-triggered runs (`@mergecraft`) are gated on the commenter's GitHub
  author association by default, extendable via `commentInvocationAllowlist`
- CI pipeline intelligence clusters failures, distinguishes flaky and
  pre-existing failures from ones the PR introduced, and blames failures to
  the hunks that caused them
- `mergecraft models|analyzers|eval|tracing|learnings|auth` CLI command
  groups; README's Action-input, Action-output, and CLI reference tables are
  generated from the live sources and CI-gated against drift
- Hardened example workflow
  (`examples/workflows/mergecraft-hardened.yml`) with a same-repo secret
  guard, wait-for-CI, and approval-check enforcement
- Release pipeline builds each image once, attaches SBOM and vulnerability
  scan reports, cosign-signs and attests the digests, then promotes tags by
  digest — no second rebuild between scan and release

### Changed

- **BREAKING** — `with: model:` is now the head of the effective model
  chain rather than a replacement for it; set `model_pin: enabled` (or
  `modelPin: true`) to restore the old single-model behavior
- **BREAKING** — comment-driven invocation under `pull_request_target` is
  refused by default; opt in with `allow_pr_target_comments: true`
- **BREAKING** — new learning entries land in a quarantined staging section
  by default instead of taking effect immediately; set
  `autopromoteLearnings: true` to restore auto-promotion
- **BREAKING** — an unrecognized `analyzers:` input value now resolves to
  the strictest tier (`untrusted-only`) instead of the most permissive
  (`auto`)

### Security

- Agent privilege drop fails closed: a run that cannot drop root aborts
  instead of continuing to execute the reviewing agent as root
- Trust tier is derived before any repo-controlled script or git setup
  runs, and an unrecognized event shape fails closed to `untrusted`
- Agent CLI subprocesses receive an explicit credential allowlist — no
  ambient GitHub tokens or inactive provider keys reach the process
- A first-party analyzer (`agentsec`) scans `.mcp.json`, `CLAUDE.md`,
  `AGENTS.md`, and skill files for policy violations, and still runs under
  `shell: disabled`
