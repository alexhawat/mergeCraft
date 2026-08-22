# Example 03 — review a patch file

Review a unified diff checked into the tree — no remote clone and no live
provider call when you pass `--dry-run`. This is the path CI forks and
air-gapped runners use.

## Live command

```bash
mergecraft review --diff patch.diff
```

## Offline command (CI-checked)

```bash
mergecraft review --diff patch.diff --dry-run
```

`patch.diff` changes `src/app.py` from `ok` to `ready`.

## Expected output

- `review-prompt.txt` — normalized dry-run prompt for the patch.
- `exit-code.txt` — `0`.

Regenerate: `make cli-examples` from the repo root.

See also: [`docs/cli-examples.md`](../../../docs/cli-examples.md).
