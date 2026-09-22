# Plan 018: Exclude managed analyzer cache from offline untracked discovery

- Status: Integrated (`021dd273`); 29 independent tests passed; final CI pending
- Issue: [#829](https://github.com/alexhawat/mergeCraft/issues/829)
- Discovered during the 2026-09-22 implementation wave at `157f57a3`.
- Priority: P2; dependencies: none.

## Verified defect

`src/mergecraft/analyzers/execution.py` provisions managed tools below
`<repo>/.mergecraft/analyzer-cache/`. `src/mergecraft/utils/offline_diff.py`
then asks Git for eligible untracked files and materializes each eligible file
with `git diff --no-index`. A consumer checkout that does not already ignore
the runtime cache can therefore include cache Python/text dependencies and
other readable cache data as if they were source additions. Binary cache files
already go through the existing binary exclusion; this plan does not claim that
binary contents are submitted. `init_cmd.py` currently scaffolds the audit and
completed-review ignore entries, while the managed producer writes both the
cache directory and `analyzers.lock`; that is not a complete defense for an
existing checkout or a checkout configured by hand.

The defect affects the default merge-base working-tree materialization and the
explicit unstaged working-tree path, both of which reuse untracked discovery.
It does not change staged diffs, explicit commit ranges, tracked-file diffs or
the analyzer cache's provisioning and integrity checks.

## Required fix and scope

Read AGENTS.md, CONTRIBUTING.md, the review doctrine and the source boundaries
above before changing code. Work in an isolated branch and use Make for checks.
Keep the filter exact: exclude a path equal to
`.mergecraft/analyzer-cache` or below `.mergecraft/analyzer-cache/` after Git's
repository-relative path normalization. Do not exclude the parent
`.mergecraft/`, a similarly named sibling such as
`.mergecraft/analyzer-cache-backup/`, or ordinary source files.

1. Add a small discovery predicate or equivalent constant in
   `utils/offline_diff.py` for the managed cache path. Apply it only to
   untracked discovery before `--no-index` patch generation so both default and
   explicit unstaged review paths are covered. Preserve the existing handling
   of symlinks, oversized files, binary data, invalid UTF-8 and gitignored
   paths.
2. Omit managed cache entries from `review.diff` without reading or classifying
   their contents and without adding one limitation per generated file. Do not
   require a new cache limitation marker: the generated runtime tree is outside
   source review, while the existing gitignored-path reporting may produce one
   collapsed cache-directory entry when the cache is ignored. Keep that existing
   reporting bounded and deterministic.
3. Do not make the filter prefix-based in a way that drops a tracked file or a
   sibling-prefix path. Tracked files under the cache path must continue to be
   represented by the normal tracked diff path, and a path such as
   `.mergecraft/analyzer-cache-backup/new.py` must remain eligible. An ordinary
   untracked source file such as `src/new.py` must remain eligible as well.
4. Update `init_cmd.py` as defense in depth with only the exact ignore entries
   for `.mergecraft/analyzer-cache/` and `.mergecraft/analyzers.lock`, and test
   their idempotence. The runtime discovery filter remains required for
   repositories that do not run `init` or already have a custom ignore policy.
   Do not add a broad `.mergecraft/` exclusion that hides repository-authored
   configuration or learnings.
5. Keep the implementation and regression scope to
   `utils/offline_diff.py`, `cli/init_cmd.py`,
   `tests/utils/test_offline_diff_untracked.py`, a new CLI init-runtime test,
   the analyzer fixture copy/build helper's cache ignore rule, and the
   Unreleased changelog entry. Do not alter analyzer provisioning or unrelated
   review paths.

## Regression and verification

Use disposable real Git repositories. Cover all of the following in focused
tests for offline diff materialization:

- nested untracked text/cache dependencies below `.mergecraft/analyzer-cache/`
  are absent from both default and explicit unstaged patches, with no cache
  file reads, findings or per-file limitations;
- a tracked file under that path, when modified, remains in the tracked diff;
- `.mergecraft/analyzer-cache-backup/new.py` and another ordinary untracked
  source file remain in the patch;
- an empty cache does not alter the result, and existing ignored, oversized,
  binary, symlink and non-UTF-8 limitation behavior remains intact;
- if the scaffold is changed, repeated `init` runs write one exact cache and
  lock ignore entry and retain the existing commit-worthy `.mergecraft` files;
- the analyzer fixture copy/build helper ignores generated cache state so test
  fixtures do not reintroduce the discovery failure.

Run the focused offline-diff, init-runtime and fixture tests through Make, then
touched-code lint and typing. Add the concise behavior note to the Unreleased
changelog. The coordinator must inspect the complete diff and rerun the
focused checks. Final `make ci`, whole-tree coverage floors and fresh shard
parity remain required before describing #829 as verified or using its closing
reference. The exclusion is intentionally limited to generated managed
analyzer cache state; broad untracked-file suppression is out of scope.
