# Security Policy

## Reporting a Vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report privately via [GitHub Security Advisories](https://github.com/alexhawat/mergeCraft/security/advisories/new).
You will receive an acknowledgement as soon as possible.

## Security response

When a private advisory is opened, maintainers follow this process:

1. **Acknowledge** the reporter (target: as soon as possible; aim for two
   business days).
2. **Triage** severity and affected versions; confirm a reproduction privately.
3. **Patch** on a private fork or embargoed branch; do not discuss the
   vulnerability in a public issue until disclosure.
4. **Release** a fix on the supported branch (`main` / `pre-0.0.1`) and
   credit the reporter unless they ask otherwise.
5. **Disclose** on the agreed date (see coordinated vulnerability disclosure
   below).

This section is the maintainer runbook. It does not replace the private
advisory form above.

## Coordinated vulnerability disclosure

mergeCraft uses **coordinated disclosure**. After a fix is available (or the
reporter and maintainers agree no fix is required):

- Publish a GitHub Security Advisory with affected versions and the
  patched release.
- Give reporters a reasonable window to confirm the fix before the advisory
  goes public.
- Do not require public proof-of-concept before acknowledgement.

## Supported Versions

This project is under active early development; only the latest `main` /
`pre-0.0.1` branch is supported.

## Review-only product boundary

mergeCraft is **review-only**. Reviewers may identify, investigate, verify,
explain, prioritize, and suggest. They must not edit source in the reviewed
tree, apply fixes, commit, push, or open a code-changing pull request.

Production modes are Review, IncrementalReview, and Plan. `mergecraft
capabilities` prints this manifest.

## Security model

mergeCraft is BYOK (bring-your-own-key/subscription): it talks directly to
the provider you configure (Anthropic, OpenAI, etc.) and never routes your
code, prompts, or credentials through a third-party SaaS backend.

- Provider credentials (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`,
  `OPENAI_API_KEY`, `CODEX_AUTH_JSON`, …) live only in your repo's GitHub
  Actions secrets and the ephemeral Action container's environment.
- `src/mergecraft/utils/secrets.py` filters sensitive env vars before they
  reach the agent subprocess (`build_agent_env` / `filter_env`) and the
  sandboxed `shell` tool (`resolve_env`); the `git` MCP tool (`_run_git`)
  still inherits the process environment and is not covered by this filter.
  See `tests/test_security_parity.py`, `tests/utils/test_secrets.py`, and
  `tests/test_security_md_residual.py` for the enforced behavior.
- `mergecraft auth claude` / `mergecraft auth codex` write secrets straight
  to `gh secret set` in the target repo — the token is never printed, logged,
  or transmitted anywhere else.
- Analyzer and static-check tooling (`actionlint`, `zizmor`, `ShellCheck`,
  `Hadolint`) run locally inside the Action container; see
  [REVIEW-CHECKS.md](REVIEW-CHECKS.md) for the full list of what a review
  checks and what it deliberately never reports.
