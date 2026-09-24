---
description: Diagnose the mergeCraft + OpenCode wiring
agent: build
---

Diagnose the mergeCraft installation and its OpenCode wiring, then report what
is broken and the exact command to fix each item.

```bash
mergecraft doctor
mergecraft provider status
opencode mcp list
```

Also check the OpenCode side: the MCP server `mergecraft` is `connected`, the
`/mergecraft/*` commands are listed, and the `mergecraft/reviewer` subagent is
available. Report failures as a short list, most severe first, with the fix.
