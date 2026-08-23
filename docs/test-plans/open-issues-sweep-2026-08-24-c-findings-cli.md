# Open issues sweep 2026-08-24 lane C — CA #452 test plan

Maps **CA RED** contracts for #452 (stable short finding id) to the test suite.
Source plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-c-findings-cli-wave-plan.md`.

## D2 — short id derived from fingerprint → CA

| Contract | Tests | Layer |
| --- | --- | --- |
| Prefix is `MC-` | `tests/analyzers/test_finding_short_id.py::test_finding_short_id_prefix_is_mc` | unit |
| Same fingerprint → same short id | `…::test_finding_short_id_is_deterministic_for_same_fingerprint` | unit |
| Default truncation matches issue example (`MC-a83f91`) | `…::test_finding_short_id_uses_fingerprint_prefix` | unit |
| Different fingerprints → different ids | `…::test_finding_short_id_differs_for_different_fingerprints` | unit |
| Unsafe fingerprint rejected | `…::test_finding_short_id_rejects_unsafe_fingerprint[*]` | unit / error |
| Truncation collision disambiguated in batch | `…::test_resolve_finding_short_ids_disambiguates_truncation_collisions` | unit |
| Collision resolution is stable | `…::test_resolve_finding_short_ids_is_stable_for_repeated_calls` | unit |
| Markdown output includes short id | `tests/findings/test_finding_short_id_outputs.py::test_render_finding_markdown_includes_short_id` | integration |
| JSON record includes short id | `…::test_finding_json_record_includes_short_id_field` | integration |
| Agent JSONL record includes short id | `…::test_finding_agent_jsonl_record_includes_short_id_field` | integration |
| PR comment body includes short id | `…::test_render_finding_pr_comment_includes_short_id` | integration |
| Same `MC-…` across all surfaces | `…::test_all_output_surfaces_share_the_same_short_id` | functional |
| `mergecraft explain MC-…` resolves packet | `tests/cli/test_explain_short_id_cmd.py::test_explain_accepts_short_finding_id` | E2E |
| Unknown short id is an error | `…::test_explain_unknown_short_id_is_an_error` (no xfail — already fail-closed) | E2E / error |

## Pinned public API (implementation wave CA)

All symbols expected in `src/mergecraft/analyzers/finding.py`:

- `FINDING_SHORT_ID_PREFIX` — `"MC-"`
- `finding_short_id(fingerprint: str) -> str`
- `resolve_finding_short_ids(fingerprints: Sequence[str]) -> dict[str, str]`
- `render_finding_markdown(finding, *, short_id: str) -> str`
- `finding_json_record(finding, *, short_id: str) -> dict[str, Any]`
- `finding_agent_jsonl_record(finding, *, short_id: str) -> dict[str, Any]`
- `render_finding_pr_comment(finding, *, short_id: str) -> str`

`lookup_finding_packet` / `mergecraft explain` must accept the short id form.

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| CA | all tests in `tests/analyzers/test_finding_short_id.py`, `tests/findings/test_finding_short_id_outputs.py`, `tests/cli/test_explain_short_id_cmd.py` except `test_explain_unknown_short_id_is_an_error` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q \
  tests/analyzers/test_finding_short_id.py \
  tests/findings/test_finding_short_id_outputs.py \
  tests/cli/test_explain_short_id_cmd.py
uv run pytest -q \
  tests/analyzers/test_finding_short_id.py \
  tests/findings/test_finding_short_id_outputs.py \
  tests/cli/test_explain_short_id_cmd.py
# expect XFAIL until CA implementation lands
```
