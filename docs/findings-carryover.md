# Finding carryover

A merged pull request keeps its inline review comments forever. Nobody re-opens
a merged pull request. So a finding mergeCraft raised, that the author neither
fixed nor rebutted, is not deleted — it is simply never read again.

Carryover turns those threads back into work. It reads a pull request's review
threads, keeps the ones that still represent open questions, and files each as
an issue keyed by the finding fingerprint the reviewer already stamps into every
inline comment.

## The two commands

```bash
# Read-only. Print what a merge would bury.
mergecraft findings export --pr 161 --format markdown
mergecraft findings export --pr 161 --format json

# Dry run: print the issues that would be filed.
mergecraft findings carryover --pr 161

# Actually file them.
mergecraft findings carryover --pr 161 --apply
```

`--repo owner/name` selects the repository; without it the commands read
`$GITHUB_REPOSITORY`. Authentication comes from `INPUT_TOKEN`, `GH_TOKEN`, or
`GITHUB_TOKEN`, in that order.

`export` never writes. `carryover` writes only under `--apply` — the bare
command prints its plan, so a repository can be swept and inspected before the
sweep is trusted with a trigger.

## What survives the merge

A thread carries over only when all of these hold:

| Rule | Why |
|------|-----|
| mergeCraft raised it | Human review threads belong to the humans who wrote them. Detected by the finding fingerprint, or the review footer on comments predating fingerprints. |
| It is still unresolved | A resolved thread is a finding the author already dealt with. `--include-resolved` overrides. |
| No human replied | A reply means somebody already ruled on the finding; re-filing it overrules them. `--include-answered` overrides. |
| Its comments were read in full | A thread longer than one page could hide a human reply past the cap, and a sweep that cannot see every reply cannot claim nobody answered. `--include-answered` overrides. |

The bar is deliberately high. A carryover issue nobody wanted is worse than a
finding that stays on the PR, because the first teaches maintainers to ignore
the label.

Threads whose anchor GitHub marked outdated **are** carried over — an outdated
anchor means the line moved, not that the concern was addressed. The filed issue
says so.

## Why re-running is safe

Idempotence rides on the **carryover key** — the pull request number plus the
finding fingerprint — not on run bookkeeping. Every filed issue embeds
`<!-- mergecraft-carryover:v1:<pr>:<fingerprint> -->` in its body, and every
sweep reads those keys back out of the `mergecraft-carryover` label first —
open **and** closed issues, because a closed one means that finding was handled
on that pull request, not lost.

Sweeping the same pull request twice therefore files nothing the second time,
which is what makes it safe on a trigger that can fire more than once.

The key is scoped to the pull request on purpose. If the same finding is
reintroduced by a *later* pull request, that is a regression and deserves its
own issue; keying on the fingerprint alone would let a long-closed issue
silently suppress it. Issues also carry a bare `mergecraft-finding` marker
alongside the key, so anything already reading finding markers still sees one.

The label is created up front rather than assumed: GitHub silently drops unknown
labels for actors without push access, and a dropped label would break the next
run's dedupe read and file duplicates forever.

Findings that predate fingerprints get one derived from path and body. It is a
stable, deterministic identity — enough for dedupe, since both sides derive it
the same way — but not necessarily equal to what a fresh stamp of the same
finding would produce, because the derivation hashes whatever the posted comment
ended up containing.

## When the sweep refuses to write

Two cases where a partial write would be worse than no write, because the
closing event that triggered the sweep does not fire again to correct it:

- **More threads than one page holds.** `--apply` refuses the whole plan rather
  than filing page one and exiting clean, which would bury everything past it.
- **An issue that could not be created.** The remaining findings are still
  attempted, but the failures are reported and the command exits non-zero, so
  the run is visibly red instead of falsely green.

## Automation

`.github/workflows/findings-carryover.yml` runs the sweep on
`pull_request_target: [closed]`, gated to merged pull requests. A pull request
closed without merging was abandoned, and its findings went with it.

**Writes are opt-in.** Set the `CARRYOVER_AUTO_APPLY` repository variable to
`true` to let merges file issues. With it unset, the automatic path runs as a
dry run and only logs what it would file — see the known gap below for why that
is the default.

The workflow never checks out or executes pull request code, and the PR number
reaches the CLI through `env:` rather than a `run:` interpolation. It needs
`issues: write`.

Note that `pull_request_target` checks out the repository's **default** branch,
not the pull request's base branch. The sweep therefore runs whatever build of
the CLI is on the default branch when the pull request closes, so
`mergecraft findings` must already be merged there for a run to do anything.

`workflow_dispatch` backfills pull requests that closed before the workflow
existed. Manual runs are dry by default; tick **apply** to file.

## Known gap

The sweep's signal is *unresolved*, which assumes the reviewer resolves the
threads it has satisfied. It does not currently do that reliably — mergeCraft's
incremental mode is instructed to reply and call `resolve_review_thread` for
findings the new commits addressed, and on PR #161 all thirteen threads were
left open, including eight the final review explicitly declared addressed.

Until that retirement step is fixed, a sweep carries over findings that were
already fixed. That is why `CARRYOVER_AUTO_APPLY` defaults to off and the
automatic path is a dry run: review what the sweep would file on your own
repository before letting merges write.
