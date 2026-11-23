# Casting exact admin search fields prevents use of ordinary database indexes

Proposed batch-002 research evidence; no human decision or human provenance.

Source: https://github.com/django/django
Introducing PR: https://github.com/django/django/pull/17885 (merged 2024-11-04T08:39:47Z).
Fixing PR: https://github.com/django/django/pull/20538 (merged 2026-01-30T16:45:39Z).

`introducing.patch` and `fix.patch` are the actual upstream PR diffs returned by GitHub's API, without edits. The patches include their associated tests and are bounded to the PRs. The source excerpts retain original line numbers and are verbatim slices of the commit-pinned upstream files. Full source hashes, excerpt ranges, and hashes are recorded in `source-snapshots.json`; full repository files are not vendored.

For a non-text field such as an indexed integer id searched via id__exact, the introducing change annotates Cast(field_name, CharField()) and filters the cast alias. On PostgreSQL an ordinary integer/primary-key index cannot serve that cast expression, causing full scans on large tables. The fix removes Cast and validates each search term against its target field before building direct lookups.

Explicit causal statement in fixing PR: This PR fixes a performance regression introduced in PR #17885.

License: BSD-3-Clause; complete upstream license text retained in `LICENSE`, fetched from https://github.com/django/django/blob/f223729f8f8380901473b244c0fc7c7dc397e3f1/LICENSE.
Copyright and attribution belong to the upstream project and its contributors as stated in that license. This fixture redistributes excerpts and patches for review/evaluation with those notices retained.

Upstream regression tests are included, not run here. No PostgreSQL query-plan reproduction or benchmark was run; index impact is explicit in the fix PR body and matches the removed Cast expression. The implementation was refactored between introducing and fixing PRs; both immutable source snapshots are included. The introducing version handles direct concrete field names (for example id__exact); do not use pk__exact to demonstrate this particular introducing hunk.
