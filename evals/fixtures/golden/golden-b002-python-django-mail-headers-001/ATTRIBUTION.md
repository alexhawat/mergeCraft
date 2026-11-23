# EmailMessage writes a caller-supplied To header twice

Proposed batch-002 research evidence; no human decision or human provenance.

Source: https://github.com/django/django
Introducing PR: https://github.com/django/django/pull/9454 (merged 2017-12-30T14:55:42Z).
Fixing PR: https://github.com/django/django/pull/18325 (merged 2024-07-11T06:00:47Z).

`introducing.patch` and `fix.patch` are the actual upstream PR diffs returned by GitHub's API, without edits. The patches include their associated tests and are bounded to the PRs. The source excerpts retain original line numbers and are verbatim slices of the commit-pinned upstream files. Full source hashes, excerpt ranges, and hashes are recorded in `source-snapshots.json`; full repository files are not vendored.

With non-empty to recipients and headers={"To": "mailing-list@example.com"}, the new list-header helper writes To from extra_headers, then the final extra_headers loop writes it again because the introducing change stops skipping To. Python email.Message assignment appends headers. The fix skips already-handled list headers and changes tests to get_all() so duplicates become visible.

Explicit causal statement in fixing PR: ticket-35033 as originally reported was caused by a regression introduced in ticket-28912 (PR #9454).

License: BSD-3-Clause; complete upstream license text retained in `LICENSE`, fetched from https://github.com/django/django/blob/da82939e5a31dea21a4f4d5085dfcd449fcbed3a/LICENSE.
Copyright and attribution belong to the upstream project and its contributors as stated in that license. This fixture redistributes excerpts and patches for review/evaluation with those notices retained.

Upstream regression tests are included, not run here. The pre-introducing version already had some duplicate-header behavior for Cc/Reply-To. The proposed defect is specifically the newly introduced To duplication, not a claim that all repeated-header variants originate in #9454.
