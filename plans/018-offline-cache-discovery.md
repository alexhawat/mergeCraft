# Plan 018: Exclude managed analyzer cache from offline untracked discovery

- Status: Planned; implementation and regression pending
- Issue: [#829](https://github.com/alexhawat/mergeCraft/issues/829)
- Discovered during the 2026-09-22 implementation wave at `157f57a3`.
- Priority: P2; dependencies: none.

## Verified defect

`src/mergecraft/analyzers/execution.py` provisions managed tools below
`<repo>/.mergecraft/analyzer-cache/`. `src/mergecraft/utils/offline_diff.py`
then asks Git for eligible untracked files and materializes each eligible file
with `git diff --no-index`. A consumer checkout that does not already ignore
the runtime cache can therefore submit provisioned binaries, receipts, staging
files or nested cache data as if they were source additions. `init_cmd.py`
currently scaffolds the audit and completed-review ignore entries; that is not a
complete defense for an existing checkout or a checkout configured by hand.

The defect is limited to the default offline working-tree materialization. It
does not change staged diffs, explicit commit ranges, tracked-file diffs or the
analyzer cache's provisioning and integrity checks.

## Required fix and scope

Read AGENTS.md, CONTRIBUTING.md, the review doctrine and the three source
boundaries above before changing code. Work in an isolated branch and use Make
for checks. Keep the filter exact: exclude a path equal to
`.mergecraft/analyzer-cache` or below `.mergecraft/analyzer-cache/` after Git's
repository-relative path normalization. Do not exclude the parent
`.mergecraft/`, a similarly named sibling such as
`.mergecraft/analyzer-cache-backup/`, or ordinary source files.

1. Add a small discovery predicate or equivalent constant in
   `utils/offline_diff.py` for the managed cache path. Apply it only to
   untracked discovery before `--no-index` patch generation. Preserve the
   existing handling of symlinks, oversized files, binary data, invalid UTF-8
   and gitignored paths.
2. When cache entries are present, expose one bounded coverage limitation for
   the managed cache root rather than enumerating unbounded binary or staging
   descendants. Keep the marker deterministic and ensure cache contents never
   enter `review.diff`. A clean repository with no cache remains free of this
   limitation.
3. Do not make the filter prefix-based in a way that drops a tracked file or a
   sibling-prefix path. Tracked files under the cache path must continue to be
   represented by the normal tracked diff path, and a path such as
   `.mergecraft/analyzer-cache-backup/new.py` must remain eligible. An ordinary
   untracked source file such as `src/new.py` must remain eligible as well.
4. If `init_cmd.py` is updated as defense in depth, add only the exact cache
   ignore entry and test its idempotence; the runtime discovery filter remains
   required for repositories that do not run `init` or already have a custom
   ignore policy. Do not add a broad `.mergecraft/` exclusion that hides
   repository-authored configuration or learnings.

## Regression and verification

Use disposable real Git repositories. Cover all of the following in focused
tests for offline diff materialization:

- nested untracked files below `.mergecraft/analyzer-cache/` are absent from
  the patch and produce exactly one bounded cache limitation;
- a tracked file under that path, when modified, remains in the tracked diff;
- `.mergecraft/analyzer-cache-backup/new.py` and another ordinary untracked
  source file remain in the patch;
- an empty cache does not produce a limitation, and existing ignored,
  oversized, binary, symlink and non-UTF-8 limitation behavior remains intact;
- if the scaffold is changed, repeated `init` runs write one exact ignore line
  and retain the existing commit-worthy `.mergecraft` files.

Run the focused offline-diff and init tests through Make, then touched-code
lint and typing. The coordinator must inspect the complete diff and rerun the
focused checks. Final `make ci`, whole-tree coverage floors and fresh shard
parity remain required before describing #829 as verified or using its closing
reference. The bounded exclusion is intentionally limited to generated managed
analyzer cache state; broad untracked-file suppression is out of scope.
