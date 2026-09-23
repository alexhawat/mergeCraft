---
name: mergecraft
description: Set up, run, and troubleshoot mergeCraft — the BYOK AI PR review GitHub
  Action and CLI. Use when the user asks to install or configure mergeCraft, add AI
  PR review to a repo, run a local review, interpret mergecraft-approval status or
  findings, configure models in .mergecraft/config.yaml, use mergecraft mcp serve,
  or debug a failing mergeCraft workflow.
compatibility: Requires uv; gh CLI optional
---
## OpenCode install

OpenCode reads skills from ``.opencode/skills/``, ``.agents/skills/``, and
``.claude/skills/``. It also supports commands (``.opencode/commands/``),
subagents (``.opencode/agents/``), and plugins (``.opencode/plugins/``).

mergeCraft ships a first-class OpenCode integration under
``integrations/opencode/``: slash commands (``/mergecraft/review`` and its
engine variants), a read-only ``mergecraft/reviewer`` subagent, and a
``mergecraft/fixer`` subagent for the review-only loop. A companion change
adds a plugin that registers the public MCP server, the commands, the agent,
and the skill automatically.

```bash
git clone --depth 1 https://github.com/alexhawat/mergeCraft /tmp/mergecraft-src
mkdir -p .opencode
cp -R /tmp/mergecraft-src/integrations/opencode/commands .opencode/
cp -R /tmp/mergecraft-src/integrations/opencode/agents   .opencode/
mkdir -p .opencode/skills
cp -R /tmp/mergecraft-src/skills/opencode/mergecraft .opencode/skills/mergecraft
rm -rf /tmp/mergecraft-src
```

Then add the ``mcp.servers.mergecraft`` block from
``integrations/opencode/opencode.jsonc`` to your ``opencode.jsonc``. OpenCode
V2 nests servers under ``mcp.servers`` and uses ``disabled`` (not the V1
top-level ``mcp`` map with ``enabled``). Or let the CLI write it:

```bash
opencode mcp add mergecraft -- mergecraft mcp serve --role public --transport stdio
opencode mcp list
```

``/mergecraft/review`` defaults to the native reviewer subagent (no mergecraft
provider tokens). ``/mergecraft/review-deep`` runs the full engine —
deterministic analyzers, JEV screen, verifier, and evidence packet. JEV and
Logfire are configured with ``mergecraft jev enable`` and
``mergecraft auth logfire``; when a Logfire token is present the plugin also
traces native reviews. See ``docs/opencode.md``.
# mergeCraft

mergeCraft is an AI-powered PR reviewer: a GitHub Action plus a Python CLI
(`mergecraft`). BYOK — the user's Claude/ChatGPT subscription or API key; no
SaaS backend. Deterministic analyzers run first, then an LLM review agent, then
a read-only verifier; typed findings drive inline comments and the
`mergecraft-approval` commit status.

## Setup checklist (new consumer repo)

1. **Prereqs:** Python **3.11+**, uv, authenticated `gh` CLI. If no Python 3.11+
   locally → use the Docker Action only ([`docs/install.md`](https://github.com/alexhawat/mergeCraft/blob/bb865d5c8e03d97269cb5100656bf047fcd22c65/docs/install.md)).
2. **Install:**

   ```bash
   uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
   mergecraft init
   ```

3. **Authentication — STOP and ask the user.** Use `mergecraft provider list`
   to find the configured provider label or id from `init`. Authenticate that
   entry with `mergecraft provider auth <label-or-id> --scope local` for local
   evaluation, or `--scope github` to adopt GitHub Actions. Examples below assume
   these provider labels are configured:
   - `mergecraft provider auth anthropic --scope github` (Claude Pro/Max)
   - `mergecraft provider auth openai --scope github` (ChatGPT Plus/Pro/Team/Enterprise)
   - `mergecraft provider auth cursor --scope github` / `mergecraft provider auth google --scope github` / API-key providers

   Never handle raw credentials; never commit secrets. GitHub scope checks the exact
   target repository before collecting credentials and stores Actions secrets.
   Local scope writes only the displayed `.env` file and never calls GitHub.
4. Commit `.mergecraft/config.yaml`, `.mergecraft/learnings.md`,
   `.github/workflows/mergecraft.yml`, and any `.gitignore` lines `init` added;
   push; open a PR or run `workflow_dispatch`. The default workflow does not
   listen for `@mergecraft review` comments.

## Standalone installation links

Install the generated `skills/<harness>/mergecraft/SKILL.md` package. The raw
`skills/mergecraft/SKILL.md` is a generator template; replace a copied template
with the generated package to repair relative links. Documentation currently
uses verified commit `bb865d5c8e03d97269cb5100656bf047fcd22c65`, because Action tag
`v0.1.0a1` predates the MCP documentation. Release maintainers can set
`MERGECRAFT_AGENT_PACKAGES_REF` when generating packages for another verified ref.
Fetch that ref first: an unresolved explicit override fails instead of silently
substituting a branch.

## CLI quick reference

| Command | Purpose |
|---------|---------|
| `mergecraft init` | Scaffold config + workflow |
| `mergecraft review` | Review local diff / branch changes (primary local review command) |
| `mergecraft review --dry-run` | Print prompt, no LLM call |
| `mergecraft review --json out.json` | Machine-readable findings |
| `mergecraft provider auth … --scope github` | Interactive provider login → `gh secret set` |
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
[`docs/mcp.md`](https://github.com/alexhawat/mergeCraft/blob/bb865d5c8e03d97269cb5100656bf047fcd22c65/docs/mcp.md) for copy-paste `mcpServers` JSON. Six tools only
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
- **Full docs:** [`README.md`](https://github.com/alexhawat/mergeCraft/blob/bb865d5c8e03d97269cb5100656bf047fcd22c65/README.md), [`AGENTS.md`](https://github.com/alexhawat/mergeCraft/blob/bb865d5c8e03d97269cb5100656bf047fcd22c65/AGENTS.md),
  [`REVIEW-CHECKS.md`](https://github.com/alexhawat/mergeCraft/blob/bb865d5c8e03d97269cb5100656bf047fcd22c65/REVIEW-CHECKS.md), [`docs/`](https://github.com/alexhawat/mergeCraft/blob/bb865d5c8e03d97269cb5100656bf047fcd22c65/docs/README.md).
