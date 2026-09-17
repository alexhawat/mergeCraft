**Reviewed changes** — privilege drop now wraps the agent argv with setpriv.

- **Wrap agent command** — `wrap_agent_command` prepends `setpriv --reuid/--regid`.

<!--
mergeCraft review metadata
- Mode: Review (initial)
- Files reviewed: 1
-->

### 🚥 Pre-merge checks

| Check | Status | Notes |
| --- | --- | --- |
| Title | ✅ | Names the privilege-drop change. |
| Description | ⚠️ | Omits the HOME redirect. |
| Linked issues | ⏭️ | None linked. |

### ⚠️ Privilege drop leaves `$HOME` root-owned

The subprocess drops uid and gid but still inherits the container root home directory. A later write into `$HOME` fails with `EACCES`.

```
setpriv --reuid=agent --regid=agent -- claude
```

<details><summary>Technical details</summary>

````markdown
## Affected sites
- src/mergecraft/utils/privilege.py:12 — setpriv without HOME

| Path | Line | Symptom |
| --- | --- | --- |
| src/mergecraft/utils/privilege.py | 12 | EACCES on config write |
````

</details>

### Findings

| Severity | Path | Message |
| --- | --- | --- |
| Critical | src/mergecraft/utils/privilege.py | HOME stays root-owned after setpriv |

This pull request must not merge until the HOME redirect lands.

- The agent cannot write MCP config after the drop.
- A second write path in `write_mcp_config` has the same ordering bug.
