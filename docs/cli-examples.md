# Runnable CLI examples

Worked examples for `mergecraft review` offline — each directory under
`examples/cli/` is a complete mini worktree you can copy or run in place.

**Audience:** consumer

Every example ships:

- `README.md` — what it demonstrates, the live command, and the offline CI path
- files under review (source or `patch.diff`)
- `.mergecraft/config.yaml` with analyzers disabled for fast, deterministic runs
- `run.sh` — executable entry point (no provider credentials)
- `expected/` — committed golden output compared by `make cli-examples-check`

CI runs the offline half only (`--dry-run` or exit-code fixtures per D12). The
live command in each README is what you run locally after `mergecraft auth …`.

## Examples

| Directory | Shows | CI-checked command |
| --- | --- | --- |
| [`examples/cli/01-review-local-diff/`](../examples/cli/01-review-local-diff/) | Uncommitted working-tree diff | `mergecraft review --dry-run` |
| [`examples/cli/02-review-branch-range/`](../examples/cli/02-review-branch-range/) | `--base` / `--head` and `--range` on two commits | `mergecraft review --base HEAD~1 --head HEAD --dry-run` |
| [`examples/cli/03-review-patch-file/`](../examples/cli/03-review-patch-file/) | Unified diff file, fully offline | `mergecraft review --diff patch.diff --dry-run` |
| [`examples/cli/04-agent-jsonl/`](../examples/cli/04-agent-jsonl/) | `--agent` JSONL consumed by a reader script | `mergecraft review --diff patch.diff --agent --dry-run` |

Example 04 pins the same `protocol_version` field and JSONL event order as the DA
goldens in `tests/cli/goldens/`. Regenerate every fixture from the repo root:

```bash
make cli-examples
make cli-examples-check
```

## Exit codes

Orchestrators should branch on the process exit code, not stderr prose. The named
review exits are documented in [`docs/EXIT-CODES.md`](EXIT-CODES.md). Example 04
includes `read_agent_jsonl.py`, which prints a human verdict line from the JSONL
`verdict` event.

## See also

- [`docs/cli.md`](cli.md) — full Typer reference generated from the live CLI
- [`docs/agent-loop.md`](agent-loop.md) — five-step agent loop using `--agent`
- [`docs/workflows.md`](workflows.md) — GitHub Action review path
- [`docs/EXIT-CODES.md`](EXIT-CODES.md) — named exit codes
