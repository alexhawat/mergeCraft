# Analyzer pipeline — test plan

Scope: what the analyzer pipeline trusts and which line each finding points at.
This suite was authored tests-first: every contract below is asserted against an
implementation that does not exist yet, so the assertions fail for missing
behaviour, not for a broken import or a syntax error.

Authoring wave: the RED suite sub-wave of the analyzer-pipeline plan.
Implementation waves: provenance (cache and lockfile), the analyzer tool's input
boundary, attribution (diff headers and SARIF paths), and memory robustness plus
the code-scanning upload default.

Ownership: only this suite owns `tests/`. Implementation waves make these tests
green; they never edit them. When an implementation wave lands, the satisfied
assertions are reconciled (any temporary non-strict expectation removed) and the
suite is expected to end with clean, real passes.

## How to read the coverage table

Each row is one contract. "Layer" is unit, integration, or functional/E2E.
"Scenario" is happy path, edge, or error. A contract may appear in more than one
row when it is exercised at more than one layer.

## Provenance — the cache a run may execute

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| A managed binary and its matching lock row committed under the checkout are never executed | unit/integration | error | `tests/analyzers/test_provision.py::test_checkout_lock_is_recorded_but_never_authenticates` |
| A lock row whose digest matches a committed binary does not satisfy resolution | integration | error | `tests/analyzers/test_provision_cache_integrity.py::test_lock_row_does_not_authenticate_a_checkout_placed_binary` |
| A committed receipt that does not bind the archive pin and the binary digest is a cache miss | unit | error | `tests/analyzers/test_provision_cache_integrity.py::test_committed_receipt_without_the_pin_binding_is_not_a_cache_hit` |
| The managed-binary cache directory resolves outside the checkout | integration | happy | `tests/analyzers/test_provision_cache_integrity.py::test_managed_cache_directory_is_outside_the_checkout` |
| The semgrep pip cache directory resolves outside the checkout | integration | happy | `tests/analyzers/test_provision_cache_integrity.py::test_semgrep_pip_cache_directory_is_outside_the_checkout` |
| A trusted cache root that resolves inside the checkout is refused with a reason naming the tool and the cache | unit | error | `tests/analyzers/test_provision_cache_integrity.py::test_cache_root_inside_the_checkout_is_refused_with_a_named_reason` |
| That refusal reaches the run as a named skip reason with no analyzer output | functional | error | `tests/analyzers/test_provision_cache_integrity.py::test_refused_cache_root_surfaces_as_a_named_skip_reason` |
| A well-formed cache entry is still reused without re-downloading (guard) | unit | happy | `tests/analyzers/test_provision_cache_integrity.py::test_unmodified_cached_binary_is_reused_without_redownloading` |
| A mutated cached binary is discarded and re-provisioned (guard) | unit | error | `tests/analyzers/test_provision_cache_integrity.py::test_binary_mutated_after_provisioning_is_never_executed` |

The refusal case pins that the root check happens before any download: the
fixture makes the download step fail loudly, so a run that reaches it cannot
pass by accident.

## Lockfile robustness

`tests/analyzers/test_lockfile_robustness.py`.

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| A row missing `tool_id` / `version` / `sha256` is skipped, not raised, when read | unit | error | `test_read_lock_skips_a_row_missing_a_required_key` (parametrized over each key) |
| A malformed row does not take well-formed siblings with it | unit | edge | `test_read_lock_keeps_well_formed_rows_beside_a_malformed_one` |
| The pre-merge digest tolerates the same rows | unit | error | `test_lock_digest_skips_a_malformed_row_instead_of_raising` |
| A merging write skips a malformed row already on disk | integration | error | `test_merging_write_skips_a_malformed_row_already_on_disk` |
| A crash during serialization leaves the previous lock intact | integration | error | `test_failed_write_leaves_the_previous_lock_intact` |
| Concurrent merging writers still serialise | integration | edge | `test_concurrent_merging_writers_still_serialise` |

The skip tests assert a warning is emitted, because a silently dropped row is
the failure mode a lock record must not have.

## The analyzer tool's input boundary

`tests/mcp/test_analyzers.py`. Each rejection case also asserts the pipeline was
never entered, so a rejected input cannot degrade into an unscoped run.

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| A `repo_root` that is not a registered checkout is rejected with a named reason | functional | error | `test_out_of_root_repo_root_is_rejected` |
| A supplied `diff_path` that is missing is rejected, never silently ignored | functional | error | `test_missing_diff_path_is_rejected_not_silently_ignored` |
| A `diff_path` that is a directory is rejected | functional | error | `test_directory_diff_path_is_rejected` |
| A `diff_path` symlink that escapes the authorized roots is rejected | functional | error | `test_diff_path_symlink_escaping_the_roots_is_rejected` |
| Non-UTF-8 `diff_path` bytes are rejected with a reason naming the encoding check | functional | error | `test_non_utf8_diff_path_is_rejected_with_a_named_reason` |
| A `diff_path` under the run's scratch directory is accepted and reaches the pipeline | functional | happy | `test_diff_path_under_tmpdir_is_accepted` |

## Test isolation for the shared analyzer fixture

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| A run against the analyzer fixture leaves the checked-in fixture tree byte-identical | functional | edge | `tests/mcp/test_analyzers.py::test_analyzer_run_leaves_the_tracked_fixture_tree_unchanged` |

This is the one contract that cannot be satisfied by the test itself: today the
suite runs the real pipeline against the in-tree fixture and writes provisioning
artifacts into it. It is expected to be red until the fixture is bound to an
isolated copy in the same change that confines the tool's `repo_root`.

## Attribution — diff headers and renamed paths

`tests/analyzers/test_scope.py`.

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| A Git C-quoted header decodes and gets its own hunks and added lines | unit | edge | `test_quoted_unicode_header_gets_its_own_hunks_and_added_lines` |
| A path containing a space-plus-`b/` sequence resolves through the rename target | unit | edge | `test_rename_to_resolves_a_path_containing_a_space_b_prefix` |
| A quoted `+++ b/…` line decodes even when the header is plain | unit | edge | `test_quoted_post_image_path_decodes_when_the_header_is_plain` |
| An unparseable header clears the current file instead of attaching to the previous one | unit | error | `test_unparseable_header_clears_the_current_file` |

The unparseable-header case is the one that distinguishes "drop a hunk" from
"invent a finding": misattributing a hunk to the previous file is worse than
losing it.

## Attribution — SARIF URIs outside the repository root

`tests/analyzers/parsers/test_sarif.py`.

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| An out-of-root `file://` URI is never shortened to a basename that exists in the repo | integration | error | `test_file_uri_outside_the_root_is_not_shortened_to_a_basename` |
| A bare absolute path outside the root keeps its path and is labelled | integration | error | `test_bare_absolute_path_outside_the_root_keeps_its_path_and_is_labelled` |
| The root-relative escape rejection names the URI that caused it | integration | error | `test_srcroot_escape_error_names_the_uri` |
| An in-root `file://` URI still resolves repo-relative (guard) | integration | happy | `test_file_uri_inside_the_root_still_resolves_repo_relative` |

The label asserted in the first two rows is the one a consumer reads to know it
cannot anchor an inline comment.

## Attribution — the host-runner secret scanner

`tests/scripts/test_native_output_to_sarif.py` and
`tests/analyzers/test_trufflehog_scope.py`.

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| The converter emits repo-relative URIs when given a root | unit | happy | `tests/scripts/test_native_output_to_sarif.py::test_trufflehog_to_sarif_emits_repo_relative_uris_when_given_a_root` |
| Without a root the reported path is kept unchanged (guard) | unit | edge | `tests/scripts/test_native_output_to_sarif.py::test_trufflehog_to_sarif_without_a_root_keeps_the_reported_path` |
| The CI emitter publishes repo-relative URIs | integration | happy | `tests/analyzers/test_trufflehog_scope.py::test_ci_trufflehog_uris_are_repo_relative` |

## Secret-scanner fixture suppressions

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| Every intentional fixture is a named suppression carrying a reason | unit | happy | `test_confirmed_fixture_suppressions_are_named_with_a_reason`, `test_confirmed_fixture_paths_are_suppressed` |
| An unnamed file under `tests/` or `docs/` is still scanned | unit | error | `test_an_unnamed_file_is_still_scanned` (parametrized) |
| Suppression keys are literal paths, never globs | unit | edge | `test_suppression_keys_are_literal_paths_not_globs` |
| The CI emitter drops the named fixtures from the SARIF document | integration | happy | `test_ci_emit_keeps_the_confirmed_fixtures_out_of_sarif` |
| The CI emitter keeps an unnamed file in the SARIF document | integration | edge | `test_ci_emit_keeps_an_unnamed_file_in_sarif` |

## Memory stores — read tolerance and bounded audit

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| A rule that is malformed or has an unparseable timestamp is skipped per entry | unit | error | `tests/memory/test_negative_memory.py::test_malformed_rule_entries_are_skipped_per_entry` |
| An audit entry gets the same per-entry tolerance | unit | error | `tests/memory/test_negative_memory.py::test_malformed_audit_entries_are_skipped_per_entry` |
| The audit trail is bounded and drops the oldest entries first | unit | edge | `tests/memory/test_negative_memory.py::test_audit_trail_is_bounded_and_drops_the_oldest_first` |
| A store that cannot be read reports every finding | integration | error | `tests/memory/test_wiring.py::test_unreadable_memory_store_reports_every_finding` |
| An unexpected store-construction failure also reports every finding | integration | error | `tests/memory/test_wiring.py::test_memory_store_construction_failure_reports_every_finding` |
| An untrusted tier still skips repo memory entirely (guard) | integration | error | `tests/memory/test_wiring.py::test_untrusted_tier_skips_repo_memory_suppression` |

For a suppression store, failing open means more findings, never fewer.

## The code-scanning upload default

| Contract | Layer | Scenario | Test |
| --- | --- | --- | --- |
| The Action input declares no default | functional | edge | `tests/action/test_action_yml_contract.py::TestActionYmlHygiene::test_sarif_upload_declares_no_default`, `tests/analyzers/test_sarif_upload.py::test_action_manifest_does_not_force_the_sarif_upload_flag` |
| The description carries no expression syntax | functional | edge | `tests/action/test_action_yml_contract.py::TestActionYmlHygiene::test_sarif_upload_description_carries_no_expression` |
| With the input absent, a repo-level opt-in enables the upload | integration | happy | `tests/analyzers/test_sarif_upload.py::test_unset_action_input_defers_to_repo_config` |
| The resolver still fails closed on an unrecognised value (guard) | unit | error | `tests/analyzers/test_sarif_upload.py::test_flag_resolution_defaults_off_and_fails_closed` |

The declared-default parser sweep in `TestDeclaredDefaultsParse` no longer lists
the upload input, because a declared default is exactly what this contract
forbids.

## Expected state at authoring time

The new assertions fail for missing behaviour, not for a collection or import
error. The new cases that are guards for behaviour already present (cache reuse,
in-root URI resolution, unnamed-file scanning, concurrent writers, the resolver's
fail-closed path) pass from the start.

Reconciliation is pending on the implementation waves: the temporary expectations
introduced here are removed as each wave lands, leaving only real passes.
