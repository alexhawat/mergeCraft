# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- CLI offline reviews now derive a trust tier from review-source provenance; cloned or out-of-root paths review at untrusted tier unless the operator passes an explicit `--trust` override
- Executable repo config (`setupScript`, `prepushScript`, `stopScript`, `staticChecks[].command`) from an untrusted review source is ignored; declarative config still applies
- Third-party clone acquisition is bounded and credential-safe: HTTPS GitHub URLs only, no redirect following, no submodule recursion by default, size and file-count ceilings, symlink/path containment, tokens never persisted in `.git/config` or process argv
- Added `mergecraft review` to target any local worktree, public GitHub repo, or private repo (with `--token` / `GH_TOKEN` / `gh auth token`), with `--head`, `--base`, `--staged`, `--unstaged`, and `--range` diff selection; `diff-review` remains as a hidden alias

### Added

- Added: a test-only provider-harness fixture schema and strict matcher
  (`tests/support/provider_harness`) so deterministic review tests can name
  the exact provider interaction they expect. Not used in production.
- Added: provider-harness recording workflow and operator docs
  (`docs/dev/provider-harness.md`); opt-in sanitized capture under
  `.ignorelocal/provider-harness/records/`.
- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews
- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy (D13)
- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win
- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache
- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets
- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default (D11)
- `mergecraft plan` previews model chain, toolset, analyzer detection, and token estimate without provider calls
- Run manifest fingerprints (model/CLI versions plus prompt, config, and policy hashes) for reproducible offline reviews
- `mergecraft review` machine contract: distinct process exit codes per `RunOutcome`, `--format text|json|jsonl|sarif`, and `--agent` JSONL streaming with an explicit `protocol_version`
- Added review-wide trace correlation: a `review.id` on every span across every process and agent of one logical review, plus a deterministic `review.correlation_key` (`sha256(repo|pr|head_sha)`) that groups re-reviews of the same commit; `trace_id` remains per agent run
- Added tracer baseline attributes (`mergecraft.run_id`, `mergecraft.version`, `mergecraft.trust_tier`, VCS and CI fields) merged into spans at close time, with explicit attributes taking precedence
- Added review-context env propagation into spawned agent CLI subprocesses, so subagent runs join the parent review's trace identity
- Added a content-capture policy for model payloads (`tracing.content`: `off` / `metadata` / `redacted` / `full`, default `redacted`; env `MERGECRAFT_TRACING_CONTENT`) gating whether LLM bodies may be emitted onto spans, with per-payload size counts and a sha256 of the original at every level above `off`
- Security: spans from untrusted sources are hard-capped at `metadata` content capture — prompt/completion bodies can never be shipped to a sink for an untrusted review, and the cap cannot be overridden by config or env
- Added model-parameter and payload capture on LLM spans (`gen_ai.request.*` / `gen_ai.response.*` / `gen_ai.usage.*`), recording both the requested and executed model so fallbacks are visible, with extended-thinking capture gated by the content policy and per-harness coverage documented (CLI harnesses have no payload visibility; the OpenCode HTTP path and stream consumer do)
- Added richer tool-call tracing: `gen_ai.tool.call.id` correlating request and response, per-call duration, and an MCP-vs-native origin distinction
- Added outcome spans: review-phase spans, per-agent run spans with MCP-stamped attribution (`MERGECRAFT_AGENT_ID`) so tool calls chain under their agent, fingerprint-keyed finding lifecycle spans, a verdict span with a derived disagreement flag, and eval-score spans that inherit the active `review.id`
- Added benchmark quality metrics: blocker precision scored separately from overall precision, semantic duplicate rate, unique accepted findings per lens, judge value (noise removed and recall lost), p50/p95 cost-latency summaries, and orchestrator kind as a scored dimension
- Added an adversarial eval corpus (`evals/cases/adversarial/`) proving the prompt-injection fence holds against hostile PR bodies, review comments, and commit messages, and that poisoned context can neither suppress real findings nor manufacture approvals
- Added `mergecraft eval gate` — a release regression gate comparing a candidate result set against baseline with a declared tolerance band, wired as a blocking job in the release workflow
- Added agent registry binding model, prompt, toolset and budget per role with `mergecraft agents list|show|set` and `make agents-check`
- Added registry-driven harness render for Claude, OpenCode, Codex, Gemini, and Cursor with per-agent models and declared Codex degradation in run metadata
- Added typed specialist handoff, model-diversity policy for verification, and ensemble or shadow dispatch modes on agent bindings
- Added change classifier and risk-based lens routing with recorded per-lens reasons in Review mode
- Promoted 20 themed review lenses from Review prose into registry entries with `mergecraft lens list|show|test`
- Added pluggable orchestrator with declarative pipeline file, trust gate for untrusted sources, and `mergecraft pipeline lint|show|explain`
- Added declared decision nodes for hybrid orchestration — typed triviality, lens selection, and finding disposition seams with pipeline-owned control flow

### Fixed

- Fixed `mergecraft review --format jsonl|sarif` writing empty output files and exiting 0 even with blockers — the CLI now threads a structured-findings sink through to the review so jsonl/sarif writers see real findings (#242 / `mergecraft-finding:v1:3f363546e98dad517048b8b9`)
- Fixed the empty-diff early return in `run_offline_diff_review` silently reporting `RunOutcome.passed` when `apply_diff_line_budget` fully truncated (or untrusted-path filtering emptied) the diff; the run now applies the scope-reduction downgrade and reports `inconclusive` (D12) (#242 / `mergecraft-finding:v1:2e1cb9c2153087658c3481bd`)
- Fixed `mergecraft review` default text mode never producing exit codes 10/11 — the CLI now requests structured findings internally so a CI script running `review` can block on the documented exit-code contract (#242 / `mergecraft-finding:v1:7a3cdf5ef1994610113e8e37`)
- Fixed `mergecraft plan` reporting `diff_path` that pointed at a path inside a torn-down `TemporaryDirectory`; the materialized diff is now persisted to `<repo>/.mergecraft/plan-review.diff` so the report's `diff_path` is reachable after return (#242 / `mergecraft-finding:v1:e8bc195570ae6f1cc8ab5bc6`)
- Fixed tool-call budget exhaustion only surfacing as a JSON-RPC error to the agent — `BudgetTracker` now records the `BudgetExhausted` it raises (`last_exhausted`) and `main._finalize` drains the tracker at finalize time, so a run that exhausts its tool-call budget is tagged `inconclusive` rather than approving on a partial signal (D12) (#242 / `mergecraft-finding:v1:aeb5d964c1d35e5a41784ded`)
- Fixed eval corpus run directories splitting on slashes in model slugs (e.g. `openrouter/openai/gpt-5`) — run ids are sanitized to a single flat component (#219)
- Fixed live corpus reviews running in an empty scratch directory — the case's repo context is materialized before the review (#220)
- Benchmark result sets now record full version pins and a reproducibility digest, so same-commit runs are comparable (#140)
- Two ensemble models that both report no findings no longer escalate to a judge (#238)
- Reviews of Python repositories with `shell: disabled` no longer fail closed after a completed review just because dependency installation was skipped as a security policy
- Fixed: model-chain fallback now advances when the provider succeeds without a terminal verdict; a valid `request_changes` is a usable result and does not trigger fallback
- Fixed: explicit `harness:` now selects the runtime agent, not only span labels
- Fixed: a previously recorded `approve` is re-validated before GitHub publish, so a later confirmed blocker cannot ship an `APPROVE` review
- Fixed: body-only `create_pull_request_review` with `approved: false` no longer posts a GitHub `APPROVE`
- Fixed: `create_pull_request_review` now requires established review scope in Review modes, matching `submit_review_verdict`

### Changed

- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`
- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

### Added

- Added: optional `harness` setting (`opencode` / `codex` / `claude` / `gemini` / `cursor`) to select the agent runtime independently of provider/model. Existing configs with the key unset keep today's inference
- Added: terminal-verdict protocol shadow mode (`gates.terminal_verdict`, default `shadow`) with a closed `VerdictDiagnostic` vocabulary; enforce still applies the fail-closed missing-verdict branch
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

### Security

- Reviewer and verifier now hold distinct, class-derived MCP toolsets; the live
  MCP server exposes those surfaces at `/mcp/reviewer` and `/mcp/verifier`,
  mutating tools stay off both except `checkout_pr` on the reviewer, and
  finding-verdict persistence stays orchestrator-only

### Fixed

- Fixed: terminal-verdict shadow mode now records a predicted outcome beside the legacy result on the live finalize path
- Fixed: a body-only COMMENT is no longer recorded as `request_changes`, and body-only `request_changes` is rejected unless it has real findings
- Fixed: publication must match the recorded terminal verdict and is re-validated before sending `APPROVE`
- Fixed: IncrementalReview `report_progress` no longer advances the model chain
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

- Typed `ProviderConfig` for OpenAI-compatible gateways (capabilities declarative; API keys stay in env vars). No wire-format change to generated `opencode.json`
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
