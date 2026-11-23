# Cycle tracking crashes the debugger on unhashable exception instances

Proposed batch-002 research evidence; no human decision or human provenance.

Source: https://github.com/pallets/werkzeug
Introducing PR: https://github.com/pallets/werkzeug/pull/1540 (merged 2019-05-12T14:55:29Z).
Fixing PR: https://github.com/pallets/werkzeug/pull/1542 (merged 2019-05-12T23:38:51Z).

`introducing.patch` and `fix.patch` are the actual upstream PR diffs returned by GitHub's API, without edits. The patches include their associated tests and are bounded to the PRs. The source excerpts retain original line numbers and are verbatim slices of the commit-pinned upstream files. Full source hashes, excerpt ranges, and hashes are recorded in `source-snapshots.json`; full repository files are not vendored.

The newly added memo.add(exc_value) hashes the exception instance. A legitimate exception class with __hash__ = None raises TypeError while the debugger is formatting the original exception. The fix tracks id(exc_value), preserving cycle detection without requiring hashable exceptions.

Explicit causal statement in fixing PR: fix minor regression introduced in #1540

License: BSD-3-Clause; complete upstream license text retained in `LICENSE`, fetched from https://github.com/pallets/werkzeug/blob/bdc17e4cd10bbb17449006cef385ec953a11fc36/LICENSE.rst.
Copyright and attribution belong to the upstream project and its contributors as stated in that license. This fixture redistributes excerpts and patches for review/evaluation with those notices retained.

Upstream regression tests are included, not run here. The case targets debugger availability/correctness and makes no security claim.
