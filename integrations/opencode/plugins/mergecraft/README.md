# mergeCraft OpenCode plugin

Wires mergeCraft into the OpenCode V2 lifecycle. Install by copying this
directory to `.opencode/plugins/mergecraft/`, or list it explicitly in
`opencode.jsonc` to pass options.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [
    {
      "package": "./.opencode/plugins/mergecraft",
      "options": { "engine": "native", "mcp": true, "logfire": true, "redact": true }
    }
  ]
}
```

## Options

| Option | Default | Meaning |
|--------|---------|---------|
| `engine` | `"native"` | Engine behind `/mergecraft/review`: `native`, `cli`, `deep`, `mcp`, or `quick`. |
| `mcp` | `true` | Register the public mergecraft MCP server (`mcp.servers.mergecraft`). |
| `logfire` | `true` | Emit one Logfire span per native review when a write token is present. |
| `redact` | `true` | Redact credential-shaped strings from prompts before admission. |
| `reviewerAgent` | `"mergecraft/reviewer"` | Reviewer subagent id. |

## What it does

**Transforms**

- `ctx.mcp.transform` — registers `mergecraft mcp serve --role public --transport stdio`. No hand-edited `opencode.jsonc` needed.
- `ctx.command.transform` — when `engine` is not `native`, installs a programmatic `mergecraft/review` that routes to the chosen engine (markdown command stays native otherwise).

**Hooks**

- `session.prompt` — redacts GitHub tokens, API keys, Logfire tokens, AWS keys, and PEM private keys before the prompt is admitted.
- `session.context` — for the reviewer subagent only, appends the mergeCraft review doctrine, removes `write`/`edit`/`patch` from the toolset, and sets `temperature: 0.2`.
- `permission.evaluate` — for the reviewer subagent only, forces `edit` and `shell` to `deny`. A configured `deny` is final and is never weakened. `allow`/`ask` decisions are the only ones this hook can change.
- `shell.create.before` — bounds `mergecraft` shell timeouts at 15 minutes.
- `tool.execute.before` / `tool.execute.after` — records a `mergecraft.review.native` span per reviewer subagent run, paired by tool call id (FIFO per session when the runtime provides none) so overlapping reviews do not overwrite each other.

## Logfire

When `MERGECRAFT_LOGFIRE_TOKEN` (or `LOGFIRE_TOKEN`) is set, native reviews emit
one OTLP span to `logfire-{us,eu}.pydantic.dev/v1/traces`, selected by
`MERGECRAFT_TRACING_REGION` (default `us`). The write token is the Bearer
credential; Logfire derives the project from it. Failures are logged and never
propagate.

If another OpenCode plugin (or environment `OTEL_*` variables) already exports
OpenCode telemetry to Logfire, set `logfire: false` to avoid a duplicate span —
the ambient exporter already covers the reviewer subagent session.

## Compatibility

V2 only. The plugin uses the `Plugin.define` entrypoint from `@opencode/plugin`
`^2.0.0` and requires OpenCode `>=2.0.0`; V1 plugin implementations do not run
in V2, so there is no V1 `server()` fallback here. See the OpenCode V1→V2 plugin
migration guide if you need a V1 port.
