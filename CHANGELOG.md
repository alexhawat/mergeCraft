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

- Wire D7 sandbox planning into adapter execution; fail-closed trust tier when the GitHub
  event is missing; redact analyzer artifacts before persist; apply repo ``inlineBudget``;
  extract canonical ``analyzers/pipeline.py``; use baked binaries when ``MERGECRAFT_ANALYZERS=full``.

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
- Initial mergeCraft snapshot from pullfrog-py (history-free rebrand).
