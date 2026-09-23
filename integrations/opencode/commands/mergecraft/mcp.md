---
description: Connect or inspect the mergeCraft MCP server in OpenCode
agent: build
---

Connect the mergecraft public MCP server to this project, or inspect an existing
connection.

```bash
opencode mcp add mergecraft -- mergecraft mcp serve --role public --transport stdio
opencode mcp list
```

The six tools are `review_change`, `get_review`, `inspect_finding`,
`explain_finding`, `get_capabilities`, and `get_policy`. They are review-only:
none of them commits, pushes, or edits the reviewed tree.

If `opencode mcp list` reports the server as needing authentication, this is the
public stdio profile and it does not — re-check that `--transport stdio` and
`--role public` are both present. The Bearer-authenticated runtime harness at
`/mcp/reviewer` is a different profile and is not for OpenCode.
