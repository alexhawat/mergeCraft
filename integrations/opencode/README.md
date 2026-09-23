# mergeCraft for OpenCode

First-class [OpenCode](https://opencode.ai) integration for mergeCraft: review
commands, a read-only reviewer subagent, an auto-registered MCP server, and a
plugin that wires all of it into the OpenCode lifecycle.

OpenCode is the generic, multi-provider harness mergeCraft already supports
(`harness: opencode`). This directory makes the relationship symmetric: OpenCode
can drive mergeCraft, and mergeCraft can run on OpenCode.

## What you get

| Surface | Path when installed | Purpose |
|---------|---------------------|---------|
| Commands | `.opencode/commands/mergecraft/*.md` | `/mergecraft/review`, `/mergecraft/review-deep`, … |
| Reviewer subagent | `.opencode/agents/mergecraft/reviewer.md` | Read-only native review, no mergecraft CLI required |
| Fixer subagent | `.opencode/agents/mergecraft/fixer.md` | Applies findings; mergecraft re-reviews (review-only preserved) |
| MCP server | `opencode.jsonc` → `mcp.servers.mergecraft` | Six review-only tools over stdio |
| Plugin | `.opencode/plugins/mergecraft/index.ts` | Auto-registers MCP, commands, agent, skill; hooks |
| CLI installer | `mergecraft opencode install` / `doctor` | One-step copy, config patch, and diagnosis |

If you only want the MCP tools, skip to [MCP only](#mcp-only).

## Engines

`/mergecraft/review` is configurable. Pick an engine per invocation, or set the
default in the plugin options.

| Engine | Command | What runs | Needs |
|--------|---------|-----------|-------|
| `native` *(default)* | `/mergecraft/review` | The `mergecraft/reviewer` subagent reads the diff and grades it | Nothing beyond OpenCode |
| `cli` | `/mergecraft/review-cli` | `mergecraft review --agent` (JSONL findings) | mergecraft CLI |
| `deep` | `/mergecraft/review-deep` | mergecraft analyzers + LLM reviewer + verifier + evidence | mergecraft CLI + a provider |
| `mcp` | `/mergecraft/review-mcp` | Public MCP `review_change` → `inspect_finding` | mergecraft CLI + MCP server |
| `quick` | `/mergecraft/review-quick` | Deterministic analyzers only, no LLM call | mergecraft CLI |
| `thirdparty` | `/mergecraft/review-thirdparty <provider/model>` | Pins a third-party gateway on the `opencode` harness, then `deep` | mergecraft CLI + endpoint |

The default engine is `native` because it costs no mergecraft provider tokens.
`deep` is the engine to reach for when a change is high-stakes: it adds the
deterministic analyzers, the JEV screen, the verifier, and the evidence packet.

## Install

### One-step install

```bash
uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
mergecraft init                      # if the repo is not set up yet
mergecraft opencode install          # commands, agents, plugin, MCP block, harness
mergecraft opencode doctor --strict  # verify
```

`mergecraft opencode install` copies the assets into `.opencode/`, writes the
`mcp.servers.mergecraft` block, and sets `harness: opencode`. Add `--global` to
install into `~/.config/opencode/` instead of the project.

Then install the skill so future sessions keep the knowledge (OpenCode reads
`.opencode/skills/`, `.agents/skills/`, and `.claude/skills/`):

```bash
git clone --depth 1 https://github.com/alexhawat/mergeCraft /tmp/mergecraft-src
mkdir -p .opencode/skills
cp -R /tmp/mergecraft-src/skills/opencode/mergecraft .opencode/skills/mergecraft
rm -rf /tmp/mergecraft-src
```

### Manual install

If you would rather copy files yourself, see
[`docs/opencode.md`](../../docs/opencode.md#install) for the commands, agents,
plugin, and MCP paths.

## MCP only

OpenCode V2 nests servers under `mcp.servers` and uses `disabled` (not
`enabled`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "mergecraft": {
        "type": "local",
        "command": ["mergecraft", "mcp", "serve", "--role", "public", "--transport", "stdio"]
      }
    }
  }
}
```

Or from the CLI:

```bash
opencode mcp add mergecraft -- mergecraft mcp serve --role public --transport stdio
opencode mcp list
```

The six tools are `review_change`, `get_review`, `inspect_finding`,
`explain_finding`, `get_capabilities`, and `get_policy`.

## JEV and Logfire

Both are OpenCode commands as well as CLI features:

```bash
mergecraft jev enable          # writes jev.enabled: true, prompts for TYPESAFE_API_KEY
mergecraft jev status          # config, credential presence, effective values

mergecraft auth logfire                                # local: writes MERGECRAFT_LOGFIRE_TOKEN + project to .env
mergecraft tracing logfire enable --scope local        # reads the token from .env
mergecraft tracing logfire wire-workflow --region eu --apply   # CI: patch the mergecraft workflow
```

- **JEV** is the pre-LLM screening gate. It is a *shadow* ranker today —
  `predict_jev_action` returns `enforced=False`, so it never withholds a unit
  from the reviewer or blocks a merge. Treat it as ranking and annotation.
- **Logfire** receives mergecraft's `llm.call` and stage spans. The plugin also
  emits a span for each *native* review when a Logfire token is in the
  environment, so native and `deep` reviews land in one project.

## Compatibility

Targets OpenCode V2. The plugin uses the V2 `Plugin.define` entrypoint and can
carry a V1 `server()` export for mixed fleets; see
[`docs/opencode.md`](../../docs/opencode.md) for the API surface it relies on.

## Contributing

This directory is mergeCraft-owned. Edit the sources here, not a copied
`.opencode/` tree. See [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).
