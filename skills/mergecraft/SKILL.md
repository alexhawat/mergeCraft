---
name: mergecraft
description: Set up, run, and troubleshoot mergeCraft — the BYOK AI PR review GitHub Action and CLI. Use when the user asks to install or configure mergeCraft, add AI PR review to a repo, run a local review, interpret mergecraft-approval status or findings, configure models in .mergecraft/config.yaml, use mergecraft mcp serve, or debug a failing mergeCraft workflow.
compatibility: Requires uv; gh CLI optional
---

# mergeCraft

mergeCraft is an AI-powered PR reviewer: a GitHub Action plus a Python CLI
(`mergecraft`). BYOK — the user's Claude/ChatGPT subscription or API key; no
SaaS backend. Deterministic analyzers run first, then an LLM review agent, then
a read-only verifier; typed findings drive inline comments and the
`mergecraft-approval` commit status.

## Setup checklist (new consumer repo)

1. **Prereqs:** Python **3.11+**, uv, authenticated `gh` CLI. If no Python 3.11+
   locally → use the Docker Action only ([`docs/install.md`](../../docs/install.md)).
2. **Install:**

   ```bash
   uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
   mergecraft init
   ```

3. **Authentication — STOP and ask the user** to run one of:
   - `mergecraft auth claude` (Claude Pro/Max)
   - `mergecraft auth codex` (ChatGPT Plus/Pro/Team/Enterprise)
   - `mergecraft auth cursor` / `mergecraft auth gemini` / API-key providers

   Never handle raw credentials; never commit secrets. Each auth command stores
   a GitHub Actions secret via `gh secret set`.
4. Commit only `.mergecraft/config.yaml` and `.github/workflows/mergecraft.yml`,
   push, open a PR (or comment `@mergecraft review`).

## CLI quick reference

| Command | Purpose |
|---------|---------|
| `mergecraft init` | Scaffold config + workflow |
| `mergecraft review` | Review local diff / branch changes (primary local review command) |
| `mergecraft review --dry-run` | Print prompt, no LLM call |
| `mergecraft review --json out.json` | Machine-readable findings |
| `mergecraft auth …` | Interactive provider login → `gh secret set` |
| `mergecraft models list\|show\|set` | Inspect/configure model chains |
| `mergecraft analyzers list\|detect\|run\|explain` | Deterministic analyzers |
| `mergecraft learnings active\|staging` | Inspect learnings memory |
| `mergecraft findings export` | Export unresolved findings |
| `mergecraft eval replay-bank` | Eval bank replay |
| `mergecraft mcp serve` | Start MCP HTTP server (Bearer token required) |
| `mergecraft mcp list` | List MCP tool surface for a role |

`diff-review` is a **deprecated alias** for `mergecraft review` (one stderr
warning per invocation) — teach `mergecraft review` instead.

## MCP

Two profiles — do not confuse them:

| Profile | Command | Transport | Auth |
|---------|---------|-----------|------|
| **Public product** | `mergecraft mcp serve --role public --transport stdio` | stdio JSON-RPC | None (local OS user) |
| **Runtime harness** | `mergecraft mcp serve` (default `--role reviewer`) | HTTP on ephemeral port | Per-serve Bearer required |

**Public install (Cursor, Claude Desktop, Codex, Gemini CLI, OpenCode):** see
[`docs/mcp.md`](../../docs/mcp.md) for copy-paste `mcpServers` JSON. Six tools only
(`review_change`, `get_review`, `inspect_finding`, `explain_finding`,
`get_capabilities`, `get_policy`). Registry: `mcp-name: io.github.alexhawat/mergecraft`.

**Runtime harness HTTP:** default `mergecraft mcp serve` mints a Bearer token on an
ephemeral port; omitting `Authorization: Bearer …` returns HTTP 401 / JSON-RPC
`-32600`. Reviewer tools live at `/mcp/reviewer`. Startup prints
`MERGECRAFT_MCP_BEARER=<token>` to stderr — pass that token on every HTTP request.
Optional HTTP public (`--role public` without `--transport stdio`) also requires Bearer.

## Configuration essentials (`.mergecraft/config.yaml`)

- **`models:`** ordered fallback chain, e.g.
  `["anthropic/claude-sonnet", "openai/gpt-5.3-codex"]`. Uncredentialed providers
  are skipped; transient failures fall through. `model_pin: enabled` opts out.
- **`prApproveEnabled: true`** lets trusted-tier runs submit a real APPROVE.
- **Trust tiers** are fail-closed: fork PRs and `pull_request_target` run with
  no secrets/network — do not "fix" this.
- **Learnings** in `.mergecraft/learnings.md`: new entries land in `## Staging`;
  only maintainer-associated authors promote to `## Active`.

## Troubleshooting

- **`mergecraft-approval` failing/neutral** — pure function of typed findings;
  run `mergecraft findings export` and read blocking items. Prose verdict cannot
  override a blocker.
- **Workflow did not trigger on comment** — only OWNER/MEMBER/COLLABORATOR
  commenters are authorized; authorization reads `author_association` from the
  event payload, never the comment body.
- **Model skipped** — no credential for that provider; run `mergecraft models list`.
- **Full docs:** [`README.md`](../../README.md), [`AGENTS.md`](../../AGENTS.md),
  [`REVIEW-CHECKS.md`](../../REVIEW-CHECKS.md), [`docs/`](../../docs/).
