# Open issues sweep — Batch A test plan (W1 RED)

Wave plan: `.ignorelocal/waves/open-issues-sweep-wave-plan.md`
Worktree: `mergecraft-issues-a-reliability` @ `wave/issues-a-reliability`

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W2** | `tests/agents/test_claude.py::test_claude_exit_with_empty_streams_surfaces_diagnosable_error` | `green after W2: diagnosable claude CLI exit (#15)` |
| **W3** | `tests/utils/test_status_checks.py::test_report_status_checks_posts_neutral_approval_when_review_incomplete` | `green after W3: neutral approval when review incomplete (#5)` |
| **W4** | `tests/utils/test_status_checks.py::test_report_status_checks_anchors_approval_to_pr_head_sha` | `green after W4: anchor approval check to PR head SHA (#6)` |

All cross-wave markers use `strict=False`.

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#15** | D5 — diagnosability, not guessed CLI fix | Unit | Happy path N/A | — |
| **#15** | D5 | Unit | Edge — exit 1, empty stdout/stderr | `test_claude.py::test_claude_exit_with_empty_streams_surfaces_diagnosable_error` |
| **#15** | D5 | Unit | Error — `AgentResult.error` names exit code + attempt context (model, CI / skip-permissions), not bare `claude exited N` | same |
| **#15** | D5 | Unit | Error — failure logged at WARNING/ERROR, not DEBUG-only | same |
| **#5** | W3 contract | Integration | Edge — `run_succeeded=False`, no approval | `test_status_checks.py::test_report_status_checks_posts_neutral_approval_when_review_incomplete[run_failed]` |
| **#5** | W3 contract | Integration | Edge — `run_succeeded=True`, no approval recorded | `test_status_checks.py::test_report_status_checks_posts_neutral_approval_when_review_incomplete[run_ok_no_approval]` |
| **#6** | W4 contract | Integration | Edge — `approval.sha` differs from PR head SHA | `test_status_checks.py::test_report_status_checks_anchors_approval_to_pr_head_sha` |
| **#6** | W4 contract | Integration | Functional — check summary names actually-reviewed SHA | same |

## Implementation notes for impl waves

- **W2:** Un-xfail `test_claude.py` only; leave status-check xfails until W3/W4.
- **W3:** Extend `Conclusion` with `"neutral"`; un-xfail #5 test only.
- **W4:** Un-xfail #6 test only.
