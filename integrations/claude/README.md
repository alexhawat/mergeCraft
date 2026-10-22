# mergeCraft for Claude Code

Claude Code looks for its plugin manifest and slash commands at fixed locations in the
repository, so the files stay where the host reads them. This directory is the pointer.

| What | Where it lives | Notes |
| --- | --- | --- |
| Plugin manifest | [`.claude-plugin/plugin.json`](../../.claude-plugin/plugin.json) | Names the skill and the commands below |
| Marketplace entry | [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json) | Lets `/plugin marketplace add` find the plugin |
| Slash commands | [`commands/`](../../commands) | `mergecraft-review.md`, `mergecraft-setup.md` |
| Skill | [`skills/claude-code/mergecraft/`](../../skills/claude-code/mergecraft) | **Generated** from the source skill; do not edit by hand |

Regenerate the skill after changing the source skill or `skills/harnesses.yaml`:

```bash
make agent-packages
make agent-packages-check
```

See [`../README.md`](../README.md) for where a new integration goes.
