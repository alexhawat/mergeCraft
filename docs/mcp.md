# mergeCraft public MCP

Install mergeCraft as a **product MCP** in Cursor, Claude Desktop, Codex, Gemini CLI,
or OpenCode. The public profile exposes **six review-only tools** over the same
completed-review engine as `mergecraft review` — not the 20+ GitHub primitives on the
runtime harness at `/mcp/reviewer`.

Registry namespace: `mcp-name: io.github.alexhawat/mergecraft` (generated
[`server.json`](../server.json)). Tool schemas: [`docs/mcp-tools.md`](mcp-tools.md).

**Prereqs:** install the CLI (`uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"`)
and authenticate a provider (`mergecraft auth …`). Run `mergecraft init` in the repo
you want reviewed so `.mergecraft/config.yaml` exists.

**Not in this release:** hosted HTTP remote MCP, OAuth connectors, or ChatGPT Apps /
Anthropic Connectors Directory submission. Local stdio is the supported install path;
HTTP public exists for tests and advanced wiring but still needs a per-serve Bearer token.

---

## What your agent can do

The public MCP profile gives an external agent a **verifier layer** on local changes:

| Tool | Purpose |
|------|---------|
| `review_change` | Run mergeCraft on a workspace-relative diff; persist a `CompletedReview` and return `MC-…` short ids |
| `get_review` | Load a stored review by id |
| `inspect_finding` | Resolve one finding by `MC-…` id or fingerprint |
| `explain_finding` | Same payload keys as `mergecraft explain` for one finding |
| `get_capabilities` | Read-only allowed vs forbidden actions (`capabilities_manifest`) |
| `get_policy` | Read-only gate policy for this serve context (not a setter) |

Use this when your coding agent should **ask mergeCraft to review** and **consume typed
findings** without opening the full in-run reviewer tool bag (`checkout_pr`,
`create_pull_request_review`, CI log miners, etc.).

**Runtime harness (different job):** `mergecraft mcp serve` without `--role public`
still serves the reviewer's in-run MCP surface at `/mcp/reviewer` with Bearer auth.
That path is for mergeCraft's own reviewing agent during a run — see
[`skills/mergecraft/SKILL.md`](../skills/mergecraft/SKILL.md).

---

## How to connect

All snippets below spawn:

```text
mergecraft mcp serve --role public --transport stdio
```

Stdio public uses **no Bearer token** (the OS user is the principal). Ensure
`mergecraft` is on `PATH` (e.g. `uv tool install …`).

### Cursor

Project or user MCP config (`~/.cursor/mcp.json` or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "mergecraft": {
      "command": "mergecraft",
      "args": [
        "mcp",
        "serve",
        "--role",
        "public",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mergecraft": {
      "command": "mergecraft",
      "args": [
        "mcp",
        "serve",
        "--role",
        "public",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Codex CLI

Codex stores MCP servers in `~/.codex/config.toml` (or project `.codex/config.toml` in a
trusted repo). Use a `[mcp_servers.<name>]` table — not JSON `mcpServers`:

```toml
[mcp_servers.mergecraft]
command = "mergecraft"
args = ["mcp", "serve", "--role", "public", "--transport", "stdio"]
```

### Gemini CLI

Gemini CLI MCP settings (`settings.json` or project override):

```json
{
  "mcpServers": {
    "mergecraft": {
      "command": "mergecraft",
      "args": [
        "mcp",
        "serve",
        "--role",
        "public",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### OpenCode

OpenCode `opencode.json` / `opencode.jsonc` (global or project). Local stdio servers
require `type: "local"` and a `command` array (executable plus args):

```json
{
  "mcp": {
    "mergecraft": {
      "type": "local",
      "enabled": true,
      "command": [
        "mergecraft",
        "mcp",
        "serve",
        "--role",
        "public",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### OpenAI / ChatGPT (Apps, connectors, Codex cloud)

**OpenAI-hosted surfaces** (ChatGPT Apps, connector marketplaces, cloud Codex agents)
are **not wired in this release**. There is no OAuth or remote HTTP endpoint you can
paste into ChatGPT today. Use stdio locally (Codex CLI above) or the JSONL loop
[`mergecraft review --agent`](agent-loop.md) until a hosted transport ships.

### Anthropic / Claude (connectors, Claude Desktop)

**Anthropic connector directory submission** is out of scope for this wave. **Claude
Desktop** is supported via the stdio block above — that is a local MCP spawn, not a
hosted Claude connector. For Claude Code in-terminal review, prefer
[`mergecraft review --agent`](agent-loop.md) or the packaged plugin; public MCP is
the install path for Desktop and other stdio hosts.

### HTTP public (advanced)

`mergecraft mcp serve --role public` (default `--transport http`) mounts `/mcp/public`
on an ephemeral port and prints `MERGECRAFT_MCP_BEARER=<token>` to stderr. Every
request needs `Authorization: Bearer …`. This is **not** the copy-paste path for
Cursor or Claude Desktop in 0.1.0a1.

---

## What mergeCraft will never do (public profile)

Through the **public** MCP catalog, mergeCraft **will not**:

- Commit, push, or open a code-changing pull request on your behalf
- Expose runtime harness tools (`push_branch`, `commit_changes`, `create_pull_request`, …)
- Mutate gate policy or trust tier (`get_policy` is read-only)
- Start a nested reviewer MCP that widens the tool surface onto `/mcp/public`
- Run without your provider credentials — `review_change` needs the same auth as CLI review

`get_capabilities` lists forbidden actions explicitly; jailbreak prompts must not score
a write tool as correct on this profile.

See also: [`docs/workflows.md`](workflows.md) (trust tiers),
[`REVIEW-CHECKS.md`](../REVIEW-CHECKS.md), [`docs/mcp-tools.md`](mcp-tools.md).
