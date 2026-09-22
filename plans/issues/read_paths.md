## Verified defect
Audited main `be9993367386b03f982c795ceb1d80e4a0bfcf1d` on 2026-09-22.

[`_paths_in`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/src/mergecraft/evidence/trajectory.py#L375) walks all argument strings but does not parse shell operands. Consequently a normal shell read `{'command':'cat src/app.py'}` is recorded as path `cat src/app.py`. It does not match the authoritative modified path `src/app.py`.

## Reproduction
Drive the production chain:
```python
state = init_tool_state(owner="example", name="demo", dir="/tmp/demo")
record_tool_call(
    state, tool="shell", arguments={"command": "cat src/app.py"}, ok=True, outcome_ok=True
)
record = build_trajectory_record(state, files_modified=["src/app.py"])
```
Observed `record.files_read == ['cat src/app.py']`; `audit_trajectory(record)` emits `changed-unread-file` for `src/app.py` despite that successful read.

[The existing smoke test](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/tests/evidence/test_trajectory_read_coverage.py#L61) asserts only the read_coverage boolean. The #796 fixture uses an artificial separate path field beside `command='cat'`, unlike the real shell payload, so it misses this.

## Acceptance
- Derive read paths from documented tool-specific path fields and safe parsed shell operands, with explicit behavior for cat, head/tail, sed, grep/rg and git object reads.
- Handle quotes/spaces, leading ./, option arguments, regexes, revision ranges, failed reads and compound commands without claiming unobserved reads.
- Keep modified files sourced exclusively from the run diff; do not reintroduce #796.
- Tests exercise actual shell command payloads and assert exact files_read plus final auditor output, including a genuine unread file that still reports.

Related: #796 is fixed; this is a distinct remaining read-side failure. Priority P2; effort M; fix risk medium. Implementation plan: `plans/005-shell-read-evidence.md`.
