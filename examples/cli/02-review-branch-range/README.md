# Example 02 — review a branch range

Compare two commits in a local git history with `--base` / `--head` or an
explicit `--range`. The checked-in `src/feature.py` shows the final file; `run.sh`
replays a two-commit history (`v1` → `v2`) on every run.

## Live commands

```bash
mergecraft review --base origin/main --head HEAD
mergecraft review --range origin/main..HEAD
```

## Offline commands (CI-checked)

```bash
mergecraft review --base HEAD~1 --head HEAD --dry-run
mergecraft review --range HEAD~1..HEAD --dry-run
```

## Expected output

- `review-prompt.txt` — dry-run output for `--base` / `--head`.
- `review-range.txt` — dry-run output for `--range HEAD~1..HEAD`.
- `exit-code.txt` — `0`.

Regenerate: `make cli-examples` from the repo root.

See also: [`docs/cli-examples.md`](../../../docs/cli-examples.md).
