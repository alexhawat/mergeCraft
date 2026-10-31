# mergeCraft for GitHub Copilot

Copilot reads repository skills from `.github/skills/`, so the files stay there. This
directory is the pointer.

| What | Where it lives | Notes |
| --- | --- | --- |
| Code-review skill | [`.github/skills/code-review/`](../../.github/skills/code-review) | The canonical review skill: checks, grading and tool references |
| mergeCraft skill | [`skills/copilot/mergecraft/`](../../skills/copilot/mergecraft) | **Generated** from the source skill; do not edit by hand |

Regenerate the mergeCraft skill after changing the source skill or
`skills/harnesses.yaml`:

```bash
make agent-packages
make agent-packages-check
```

See [`../README.md`](../README.md) for where a new integration goes.
