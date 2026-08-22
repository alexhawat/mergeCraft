# Example 04 — agent JSONL for orchestrators

`mergecraft review --agent` streams one JSON object per line on stdout. Each
event stamps `protocol_version` (currently `1`). Human-readable logs belong on
stderr — never redirect stdout away from the JSONL stream.

This example ships a tiny consumer (`read_agent_jsonl.py`) that parses the
stream and maps the final `verdict` exit code to a label. The golden JSONL shape
matches the DA fixtures under `tests/cli/goldens/`.

## Live command

```bash
mergecraft review --diff patch.diff --agent
```

## Offline command (CI-checked)

```bash
mergecraft review --diff patch.diff --agent --dry-run
```

`--dry-run` still emits the JSONL lifecycle (`run_started`, `phase`, `verdict`,
`run_finished`) without calling a provider.

## Branch on exit code

| Code | Meaning |
| --- | --- |
| `0` | pass |
| `10` | findings |
| `11` | blocked |
| `12` | failed |
| `20` | inconclusive |
| `30` | configuration |
| `40` | infra |
| `50` | timeout |
| `2` | usage |

Full table: [`docs/EXIT-CODES.md`](../../../docs/EXIT-CODES.md).

## Expected output

- `agent.jsonl` — normalized agent protocol stream.
- `verdict.txt` — summary printed by `read_agent_jsonl.py`.
- `exit-code.txt` — process exit from `mergecraft review --agent --dry-run`.
- `exit-code-map.txt` — quick reference for orchestrators.

Regenerate: `make cli-examples` from the repo root.

See also: [`docs/cli-examples.md`](../../../docs/cli-examples.md),
[`docs/agent-loop.md`](../../../docs/agent-loop.md).
