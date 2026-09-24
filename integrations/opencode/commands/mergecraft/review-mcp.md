---
description: Review current changes through the mergeCraft public MCP tools
agent: build
---

Review the current change using the mergecraft MCP server. $ARGUMENTS

1. `review_change` — run a read-only review and persist a durable review id.
   Pass `base`/`head` for a ref range, `diff` for a patch file, or neither for
   the working tree.
2. `get_review` — load the persisted review by id.
3. `inspect_finding` and `explain_finding` — drill into individual findings.
4. `get_capabilities` and `get_policy` — confirm the review-only contract.

If the `mergecraft` MCP server is not connected, run `/mergecraft/mcp` or add it
per `docs/mcp.md`, then retry. If it still will not connect, fall back to
`/mergecraft/review`.
