# Host integrations

`integrations/` holds the **host-facing, non-Python assets** mergeCraft ships for an
agent host: commands, subagents, plugins and config templates. Python that mergeCraft
itself imports does not live here; it stays under `src/mergecraft/integrations/` and
ships in the wheel.

| Directory | Holds | Ships as |
| --- | --- | --- |
| `integrations/opencode/` | OpenCode commands, subagents, plugin and config template | Packaged into the wheel (`mergecraft/data/opencode`) and installed by `mergecraft opencode install` |
| [`integrations/claude/`](claude/README.md) | Pointer to the Claude Code plugin manifest and slash commands | The repository root, where Claude Code reads them |
| [`integrations/copilot/`](copilot/README.md) | Pointer to the Copilot code-review skill | `.github/skills/`, where Copilot reads it |

## Where a new integration goes

- **Host assets** (commands, agents, plugins, config templates) go in
  `integrations/<host>/`, one directory per host, each with a `README.md` that says
  what it installs and how.
- **Locations a host dictates** stay where the host looks for them. Claude Code reads
  `.claude-plugin/` and `commands/` at the repository root; Copilot reads
  `.github/skills/`. Those files do not move. The host's `integrations/<host>/README.md`
  points at them instead, so there is still one place to look.
- **Agent Skills packages** are generated into `skills/<harness>/mergecraft/`; do not
  edit them by hand (`make agent-packages`, checked by `make agent-packages-check`).
- **Shipped Python** (adapters the product imports at runtime) lives in
  `src/mergecraft/integrations/`, not here. The wheel and sdist ship it from there.
