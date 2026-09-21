# Test-suite honesty — review_policy behavioural contracts

Scope: the `mergecraft.review_policy` package (`paths.py`, `manifest_names.py`,
`security_tokens.py`). Before this wave **no test file imported the package at
all**; `normalize_repo_path` builds the dedup keys that decide which findings
publish, so a normalization change silently changes what counts as a duplicate.

Worktree: `../mc-honesty` on branch `wave/test-suite-honesty`.
Owner of `tests/` and this file: `test-creator`.

All tests here are **green** against current product code; no production file
was changed. The vocabularies are asserted *through their consumers* — never by
pinning today's strings — because a legitimate vocabulary change must not fail a
test. The name sets are asserted as basename sets plus a per-name behavioural
loop, so adding a name keeps the property true while deleting a load-bearing one
fails it.

## Contract matrix

| Contract | Layer | Test node(s) |
| --- | --- | --- |
| `normalize_repo_path` table: `./`, diff `a/`/`b/`, chaining, backslashes, whitespace, case, duplicate separators, absolutes, traversal | unit | `tests/review_policy/test_paths.py::test_normalize_repo_path` |
| Two findings whose paths normalize to the same key dedup | unit (consequence) | `tests/review_policy/test_dedup_consequence.py::test_paths_normalizing_to_the_same_key_dedup` |
| Two findings whose paths do not normalize to the same key do not dedup | unit (consequence) | `tests/review_policy/test_dedup_consequence.py::test_paths_not_normalizing_to_the_same_key_do_not_dedup` |
| The dedup key is `(normalized path, start, end, category)` | unit | `tests/review_policy/test_dedup_consequence.py::test_dedup_key_is_the_normalized_path_plus_span_and_category` |
| Name sets hold bare basenames (no separators, non-empty, stripped) | unit | `tests/review_policy/test_manifest_names.py::test_name_sets_hold_bare_basenames` |
| Every lockfile name marks its file a changed lockfile in a diff | integration (scope parse) | `tests/review_policy/test_manifest_names.py::test_lockfile_names_are_load_bearing_in_diff_scope` |
| Every dependency-manifest name marks its file a changed manifest | integration (scope parse) | `tests/review_policy/test_manifest_names.py::test_dependency_manifest_names_are_load_bearing_in_diff_scope` |
| Every generator-config name lets a generated finding survive | integration (generated policy) | `tests/review_policy/test_manifest_names.py::test_generator_config_names_let_generated_findings_survive` |
| An unrelated change does not keep a generated finding | unit (negative control) | `tests/review_policy/test_manifest_names.py::test_a_generated_finding_drops_without_a_generator_config_change` |
| A security-signal message infers the Security category | unit (severity rubric) | `tests/review_policy/test_security_tokens.py::test_security_signal_messages_infer_the_security_category` |
| A security signal keeps a Critical finding uncapped | unit (severity rubric) | `tests/review_policy/test_security_tokens.py::test_security_signal_keeps_a_finding_uncapped` |
| A docs-only nit still caps without a security signal | unit (negative control) | `tests/review_policy/test_security_tokens.py::test_docs_nit_still_caps_without_a_security_signal` |
| Two paraphrases sharing one domain token on each side merge | unit (dedup) | `tests/review_policy/test_security_tokens.py::test_domain_hint_groups_merge_two_findings_in_one_domain` |
| Findings from unrelated domains stay apart | unit (dedup) | `tests/review_policy/test_security_tokens.py::test_findings_from_unrelated_domains_stay_apart` |

## Evidence the consequence test exercises the real dedup path

`test_paths_normalizing_to_the_same_key_dedup` and
`test_paths_not_normalizing_to_the_same_key_do_not_dedup` call the real entry
point `mergecraft.findings.dedup.dedupe_findings` with two `Finding` objects
that differ **only** in their path. The bucket key is built from
`normalize_repo_path` inside `findings/dedup.py`, so a path pair that collapses
(`./src/app.py` with `src/app.py`) produces one finding, while a pair the
normalizer keeps distinct (`src/app.py` with `src/other.py`, `src/App.py`,
`src//app.py`, `/src/app.py`, `../src/app.py`) produces two. Both directions are
parametrized and each asserts its normalization precondition first, so a
normalization change fails at the exact case that moved.

`test_dedup_key_is_the_normalized_path_plus_span_and_category` pins the public
`location_key` shape directly, tying the consequence back to the key.

## Known limitation pinned, not fixed

`normalize_repo_path` strips a leading `a/` or `b/` from **any** input, the
diff-prefix contract it documents. Those are valid directory names in a repo,
so a path such as `b/foo.py` normalizes to `foo.py`. This is the shipped
behaviour and is pinned as such; no caller currently passes a repo path whose
first segment is literally `a` or `b`, so no product issue was filed. A future
change that scopes the diff-prefix strip to diff-origin paths would update the
`b/foo.py` row and both `b/` consequence rows.

## Commands

```bash
uv run pytest tests/review_policy -q --strict-markers
make lint
make typecheck
```
