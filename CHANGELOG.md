# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `mergecraft diff-review --json PATH` writes structured findings validated against
  the `Finding` schema for offline benchmark/scoring workflows (#30)
- `.mergecraft/config.yaml` accepts an ordered `models` list and optional
  `modelFallbacks` map for per-slug backup chains; the legacy scalar `model` key
  still works unchanged (#14)
- `mergecraft models list`, `models set`, and `models show` CLI commands for
  inspecting the curated catalog, writing an ordered preference list, and
  previewing which slug would run (#14)
- Runtime model chain resolution: skip entries without credentials, advance on
  retryable provider failures, and log selected/skipped slugs at Action-visible
  levels (#14)
- Reviewers can list GitHub check suites for a commit via `list_check_runs` and fetch
  one suite by id via `get_check_suite`, then pass the id to `get_check_suite_logs`
  (#8)
- Configured `staticChecks` now report a `declared-but-cannot-run` row when the gate
  cannot execute in this environment (for example `shell: disabled`), instead of
  disappearing silently (#8)

### Docs

- Rewrite README with a 3-step quickstart and a dedicated Authentication section
  documenting Claude/Codex subscription auth (`mergecraft auth claude` /
  `auth codex`, `CLAUDE_CODE_OAUTH_TOKEN` / `CODEX_AUTH_JSON`) alongside API keys.
- Add OSS governance files for parity with sevn-bot/sevn: `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`,
  and `.github/ISSUE_TEMPLATE/` (bug report, feature request, security contact link).

### Fixed

- Action `model` input and explicit chain selection no longer lose to
  `MERGECRAFT_MODEL`; missing agent binaries are skipped when walking the chain;
  retryable chain advancement is wired through the Action entrypoint (#14)
- Always post the `mergecraft-approval` status check on PR runs when status checks
  are enabled; use `neutral` when the review did not complete so a failed run no
  longer leaves a missing check that branch protection can misread as pass
  ([#5](https://github.com/alexhawat/mergeCraft/issues/5)).
- Anchor the `mergecraft-approval` check to the PR head SHA and name the
  actually-reviewed commit in the check summary so stale reviews are visible
  ([#6](https://github.com/alexhawat/mergeCraft/issues/6)).
- Preserve a recorded approval conclusion when the overall run fails after the
  review step (e.g. schema enforcement), instead of masking it as `neutral`
  ([#5](https://github.com/alexhawat/mergeCraft/issues/5)).
- Surface `claude` CLI stdout/stderr, exit code, and attempt context (model,
  permissions flag, CI env) at warning level on non-zero exit; propagate the
  diagnosable error into Action failure output and the `mergecraft` check-run
  summary ([#15](https://github.com/alexhawat/mergeCraft/issues/15)).
- Learnings updates on ephemeral Action runners now log a warning instead of a false
  success and include the before→after delta in the posted review or progress comment
  so operators can commit `.mergecraft/learnings.md` deliberately ([#7](https://github.com/alexhawat/mergeCraft/issues/7)).
- Wire K3 CI intelligence to the `analyze_ci_failures` MCP tool — fetches check-suite logs,
  clusters failures, and returns review-ready `section`, `preMergeSummary`, `comments`, and
  `stats`; Review/IncrementalReview prompts call the tool instead of manual log clustering.
  ``execution.py`` orchestration; register ``buf_native`` parser; gate ``verified_only``
  findings via ``filter_for_review``; require detect-glob match for ``default_enabled``
  tools; skip managed provisioning when scoped files are empty; harden scratch path writes,
  pinned download redirects, sandbox pid-namespace requirement, and ``RLIMIT_AS`` memory cap.
- Wire D7 sandbox planning into adapter execution; fail-closed trust tier when the GitHub
  event is missing; redact analyzer artifacts before persist; apply repo ``inlineBudget``;
  extract canonical ``analyzers/pipeline.py``; use baked binaries when ``MERGECRAFT_ANALYZERS=full``.

### Changed

- **Migration:** repos not ready for the analyzer catalog should set
  ``analyzers.enabled: false`` in ``.mergecraft/config.yaml`` or ``INPUT_ANALYZERS: off`` in
  the GitHub Action until they opt in.

### Added

- Hardened reference workflow at `examples/workflows/mergecraft-hardened.yml`
  (same-repo secret guard, PR-number concurrency, wait-for-CI, base-ref fetch,
  full-SHA pin, approval-check enforcement) plus a template renderer with
  `make example-workflows-check` wired into `make ci-static`.
- Codex subscription agent harness (`agents/codex.py`): invokes the official
  `codex exec` CLI with mergeCraft MCP config, reviewer/verifier instructions,
  and the same push/shell permission gates as Claude Code; resolves when
  `CODEX_AUTH_JSON` is set; Docker image installs `@openai/codex`.
- OpenAI API key path on the Codex harness: `OPENAI_API_KEY`-only runs resolve
  to the same `codex` agent for any `openai/*` model; fail-loud when neither
  `OPENAI_API_KEY` nor `CODEX_AUTH_JSON` is configured.
- Gemini agent harness (`agents/gemini.py`): invokes the official `gemini` CLI
  with mergeCraft MCP settings; resolves when `GEMINI_API_KEY` or
  `GOOGLE_GENERATIVE_AI_API_KEY` is set for `google/*` models; Docker image
  installs `@google/gemini-cli`; `mergecraft auth gemini` saves the API key via
  `gh secret set`.
- Cursor Cloud Agent harness (`agents/cursor.py`, Phase A / D9): launches a
  remote cloud agent via the Cursor API (`CURSOR_API_KEY`); polls to terminal
  status and surfaces the dashboard URL in agent metadata; local Cursor CLI
  detection remains deferred (Phase B); `mergecraft auth cursor` saves the API key via
  `gh secret set`.
- Batch D Final gate hardening: httpx-based `auth gemini`/`auth cursor` key
  validation (Bandit-clean), usable-only `CODEX_AUTH_JSON` resolution, Gemini
  system-prompt delivery, Cursor loopback MCP omission for cloud runs, and
  dict-payload shell/branch reads for Action runs.
- CI pipeline intelligence (K1): ``PipelineProvider`` protocol with ``GitHubActionsProvider``
  (delegates ``get_check_suite_logs`` behind the provider), honest CircleCI/GitLab/Azure stubs,
  normalized failure shape with stable fingerprints, and ingest-time log redaction via
  ``analyzers/redact.py``.
- CI pipeline intelligence (K2): root-cause clustering, flaky/pre-existing detection,
  failure-to-hunk blame, explicit truncation notices, and verification routing for
  PR-attributed CI findings.
- CI review integration (K3): ``### 🚨 CI failures`` section with clustered root causes,
  flaky/blame verdicts, pre-merge CI row, inline fix suggestions for contained hunks, and
  ``REVIEW-CHECKS.md`` CI section.
- Review integration for analyzers: `run_analyzers` and `analyzer_findings` MCP tools,
  read-only `mergecraft-verifier` subagent for Critical/Major hits (D11), mechanical
  findings section and pre-merge Analyzers row, offline `diff-review` wiring, and
  `REVIEW-CHECKS.md` §2 rewrite (W7).
- GitHub-native analyzer adapters: actionlint, zizmor, ShellCheck, and Hadolint manifests
  with bundled actionlint SARIF template, ``adapters.run_adapter`` end-to-end runner, and
  fixture-repo planted-finding coverage (W6).
  suppression, and ``introduced_by_pr`` annotation for analyzer findings.
- SARIF 2.1.0 ingest and export, native parsers (ruff, eslint, osv, trivy, trufflehog,
  shellcheck), D8 redaction boundary, and file-based output parsing for large analyzer runs.
- Analyzer provisioning and sandbox: pinned managed-binary fetch with SHA256 verification,
  ``.mergecraft/analyzers.lock`` reproducibility, trust tiers wired into ``ToolContext``,
  sandbox capability probing with skip-not-degrade on missing isolation, ``Dockerfile.analyzers``
  full image tier, and ``action.yml`` ``analyzers`` input (`off` | `auto` | `full`).
- Analyzer platform core: manifest schema, catalog registry, normalized ``Finding`` model,
  execution-mode resolver, shared runner, and ``analyzers:`` config block.
- **Catalog C1:** repo-native language-gate manifests and detection for Ruff, MyPy,
  Pyright, BasedPyright, ESLint, Biome, and Oxlint — config-driven ``exclusive_group``
  selection, type-checker skip (never managed substitute), and ``analyzer_run_metadata``
  version reporting (D5/C3).
- **Catalog C2:** managed OSV-Scanner and Trivy adapters with base-vs-head CVE delta
  (``supply_chain.run_differential_scan``), TruffleHog secret scanning with rotation-first
  remediation and verify-off-by-default policy (``config.trufflehog_verify_enabled``),
  and ``dependency-vuln`` exclusive-group dedup hooks (D12).
- **Catalog C3:** pattern-scanner backend with Semgrep (pip-provisioned), swappable
  OpenGrep, and ast-grep structural rules — repo rules preferred, SARIF ingest scoped to
  changed files, and Critical/Major taint hits gated on ``mergecraft-verifier`` (D11).
- **Catalog C4:** differential contract adapters for oasdiff (OpenAPI breaking changes),
  Squawk (unsafe PostgreSQL migrations), and buf breaking/lint — base ref required (D6),
  ``oasdiff_json``/``squawk_json`` parsers, and ``contracts.run_differential_adapter``.
- **Catalog C5:** native agent-manifest security scanner for MCP and skill/instruction
  manifests — YAML policy rules, optional SkillSpector corroboration, and
  ``mergecraft.analyzers.agentsec`` manifest reader (C7 exception to manifest-only catalog).
- **Catalog C6:** P1–P3 long-tail manifests (35 tools), generated ``docs/ANALYZERS.md`` with
  CI ``catalog-check`` gate, ``docs/CONTRIBUTING-ANALYZERS.md``, and ``mergecraft analyzers``
  CLI (list/detect/run/explain/export/lock).
- Initial mergeCraft snapshot from pullfrog-py (history-free rebrand).
