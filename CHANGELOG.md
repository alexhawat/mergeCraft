# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Docs

- Rewrite README with a 3-step quickstart and a dedicated Authentication section
  documenting Claude/Codex subscription auth (`mergecraft auth claude` /
  `auth codex`, `CLAUDE_CODE_OAUTH_TOKEN` / `CODEX_AUTH_JSON`) alongside API keys.
- Add OSS governance files for parity with sevn-bot/sevn: `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`,
  and `.github/ISSUE_TEMPLATE/` (bug report, feature request, security contact link).

### Fixed

- Thermos T.1: wire C2 supply-chain CVE delta through ``run_adapter``; extract shared
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
