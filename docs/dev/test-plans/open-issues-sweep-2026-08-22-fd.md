# Open issues sweep 2026-08-22 — Batch FD test plan (#397)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md`
Worktree: `.ignorelocal/worktrees/repo-state-2026-08-22-sweep` @ `wave/repo-state-2026-08-22-sweep`
Authoring wave: **W7** (FD RED) · Implementation: **W8** (sync packaged copy if drifted)

Decision **D13**: do not delete either tree; do not require full equality of
`evals/cases/` and `src/mergecraft/evals/cases/`. Assert only that every
packaged file has a byte-identical repo-root twin at the same relative path.

## xfail schedule

No cross-wave xfails — trees are byte-identical at W7 authoring time; suite is
expected to pass green immediately.

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| FD397a | Packaged tree is non-empty | unit | error | `tests/evals/test_packaged_cases_sync.py::test_packaged_cases_tree_is_nonempty` |
| FD397b | Each packaged file exists under `evals/cases/` | unit | happy | `test_every_packaged_case_exists_under_evals_cases` |
| FD397c | Packaged bytes match repo-root copy | unit | happy + error (drift) | `test_packaged_cases_match_evals_cases_bytes` |

## W8 reconciliation

If a future edit drifts one tree, W8 makes the packaged copy match the
repo-root canonical copy (`evals/cases/`). Extra files under `evals/cases/`
remain allowed.
