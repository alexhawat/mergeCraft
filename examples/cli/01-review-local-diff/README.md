# Example 01 — review local uncommitted work

Review the edits in your working tree without posting to GitHub. This tree is a
mini Python repo: `src/calculator.py` changes between the committed baseline and
the uncommitted edit that `run.sh` applies before invoking mergeCraft.

## Live command

From this directory (after `mergecraft auth …`):

```bash
mergecraft review
```

## Offline command (CI-checked)

`run.sh` materializes a fresh git checkout, applies the uncommitted change, and
runs:

```bash
mergecraft review --dry-run
```

`--dry-run` prints the Review prompt and diff summary without calling a
provider. No API key is required.

## Expected output

- `review-prompt.txt` — normalized dry-run prompt (temp paths replaced with
  `<tmpdir>`).
- `exit-code.txt` — `0` (clean pass on an empty diff review dry-run).

Regenerate fixtures from the mergeCraft repo root:

```bash
make cli-examples
```

See also: [`docs/cli-examples.md`](../../../docs/cli-examples.md),
[`docs/EXIT-CODES.md`](../../../docs/EXIT-CODES.md).
