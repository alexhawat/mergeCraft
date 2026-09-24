# Test plan — CI, release and build-infra honesty fixes

**Scope.** The RED suite for the CI/release/build-infra wave (CI1), greeened by
the integration-lane wave (CI2), the CodeQL/release wave (CI3), and the
dependency/build wave (CI4). Every test is keyless and runs on macOS and Linux.
Every test in the "Not yet implemented" list fails on the current tree for the
reason named below; the suite collects cleanly and passes `make lint` and
`make typecheck`.

**How to run.**

```bash
make lint
make typecheck
MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/ci/test_codeql_workflow.py \
  tests/ci/test_makefile_targets.py tests/ci/test_declared_dependencies.py \
  tests/ci/test_release_dist.py tests/ci/test_in_image_test_lists.py \
  tests/ci/test_httpcore_private_api.py tests/ci/test_live_provider_http_status.py \
  tests/ci/test_pre_commit_hardening.py tests/ci/test_integration_job_ran.py \
  tests/ci/test_live_image_smoke.py tests/ci/test_live_provider_matrix.py \
  tests/ci/test_hook_pins.py -q
```

## Coverage matrix

### Integration gate honesty — `tests/ci/test_integration_job_ran.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_no_ci_meta_test_carries_integration_or_hermetic_markers` | functional | No file under `tests/ci/` may carry `integration` or `hermetic_integration`, so a meta-test can never satisfy the integration gate | The existence smoke still carries `@pytest.mark.integration` |
| `test_test_integration_selects_the_hermetic_marker` | integration | `make test-integration` selects `hermetic_integration` while keeping the `integration and not live` substring the live contract checker reads | The selector is still `integration and not live` |
| `test_hermetic_marker_is_registered_in_pytest_ini` | integration | `hermetic_integration` is a registered pytest marker | Not registered |
| `test_hermetic_integration_files_are_marked_and_skip_free` | functional | Both genuinely hermetic integration files carry the marker and contain no `pytest.skip`/`skipif` | Neither file is marked |

Greened by: the integration-lane wave (delete the smoke, register the marker,
change the selector, mark the two files). Existing `count_executed` parser tests
stay green as regression guards.

### Live provider status-first failures — `tests/ci/test_live_provider_http_status.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_provider_failure_names_status_without_key_or_url` (4 providers) | functional | Each provider test asserts the HTTP status before parsing the body; the failure names the status and leaks neither the credential nor the request URL (Gemini's key rides the query string) | Every provider parses `response.json()` first, so the failure is a body-shape assertion with no status |
| `test_provider_failure_bounds_the_body_it_echoes` | edge | At most 300 characters of the body are echoed | The full body is echoed in the Anthropic shape assertion |
| `test_nous_default_model_is_the_shared_documented_constant` | unit | The live Nous leg reads one shared `NOUS_DEFAULT_MODEL` constant equal to the documented portal default | No such constant; the test hard-codes `Hermes-4-70B` |
| `test_nous_leg_posts_the_documented_default_model` | functional | The Nous request posts the documented default model | It posts `Hermes-4-70B` |
| `test_nous_leg_model_is_env_overridable` | functional | `MERGECRAFT_LIVE_NOUS_MODEL` overrides the model | The code reads a different env var and ignores the override |

Greened by: the integration-lane test-file fixes (status-first assertions, the
shared constant, the documented model).

### Live matrix alignment — `tests/ci/test_live_provider_matrix.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_live_matrix_contains_only_runnable_legs` | integration | The nightly matrix is exactly `nous` and `github`, and every leg has a secret-env entry | Five legs, three of which need credentials the repo does not hold |
| `test_live_matrix_env_wires_exactly_the_runnable_legs` | integration | Surviving legs are wired; the removed legs' secrets are gone | The three removed secrets are still wired |

Greened by: narrowing the workflow matrix and its env block.

### E2E live slice honesty — `tests/ci/test_live_image_smoke.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_unconfigured_live_slice_warns_as_unavailable` | functional | An empty model exits 0, emits a `::warning`, records "unavailable" in the step summary, and never says "skipped" | It prints "skipped" and exits 0 with no warning or summary line |

Greened by: replacing the skip branch with warning + summary + exit 0. The
existing configured-but-missing-credential parameter stays non-zero as a
regression guard.

### Live matrix secrets and in-image pins — `tests/ci/test_in_image_test_lists.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_privilege_script_runs_the_chown_test_in_the_privileged_lane` | integration | The in-image root pass lists the chown test and exports the privileged-lane flag | The chown test is absent from every lane |
| `test_in_image_scripts_pin_the_project_test_runner` | integration | Both in-image scripts pin `pytest`/`pytest-asyncio` at the project's dev pins | The privilege script pins `pytest-asyncio==1.3.0` against the project's `1.4.0` |
| `test_disposable_host_lane_runs_the_sandbox_test_in_the_privileged_lane` | functional | A lane (workflow step or Make target) runs the sandbox test with the privileged-lane flag | No lane runs it |
| `test_every_guarded_test_consults_the_privileged_lane` (2 files) | unit | Both guarded tests consult the lane flag and call `pytest.fail` when the lane cannot satisfy them | Neither references the flag |

Greened by: the in-image list/pin edits and the host-lane target, plus the
guarded-test edits.

### CodeQL publication and failure policy — `tests/ci/test_codeql_workflow.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_analysis_failure_fails_the_job_without_gating_the_repo` | integration | No `continue-on-error` anywhere; `security-events: write` kept; triggers unchanged | The job sets `continue-on-error: true` |
| `test_upload_is_conditional_on_write_capable_events` | integration | `upload` is not unconditionally `never`; the condition excludes fork and Dependabot PRs and otherwise yields `always`, naming the exact clauses | `upload: never` |

Greened by: removing `continue-on-error` and making the upload conditional on
the write-capable event filter.

### Dist install check and provenance — `tests/ci/test_release_dist.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_build_dist_install_checks_the_wheel` | integration | `build-dist` runs `make test-wheel-corpus` | It runs bare `uv build` |
| `test_dist_provenance_covers_dist_and_reuses_the_image_pin` | integration | A dist attestation step covers `dist/*` at the same pinned SHA as the image attestations | No dist attestation exists |
| `test_build_dist_holds_the_attestation_tokens` | integration | Job permissions include `id-token: write` and `attestations: write`, and no wider | Only `contents: read` |

Greened by: swapping the build command, adding the attestation step at the image
pin, and granting the tokens.

### Build targets and tooling claims — `tests/ci/test_makefile_targets.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_docker_build_tag_is_a_valid_docker_reference` | unit | The `docker-build` tag has a lowercase repository component matching Docker's grammar | `mergeCraft:local` has uppercase and cannot be built |
| `test_sharding_claims_durations_it_has` | integration | Either the durations file exists and parses (with a refresh target) or the least-duration claim is gone | The Makefile selects least-duration with no durations file |
| `test_workflow_lint_fails_when_it_cannot_lint` | functional | Off Linux with no cached binaries the script exits non-zero and says lint is unavailable | It exits 0 saying it skipped the install |

Greened by: lowering the tag, committing/adjusting the durations claim, and
failing closed in the lint script.

### Dependency contract — `tests/ci/test_declared_dependencies.py`, `tests/ci/test_httpcore_private_api.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_every_third_party_import_is_declared` | integration | Every third-party top-level import in `src/mergecraft/` maps (through `importlib.metadata.packages_distributions()`) to a declared direct dependency or extra | `click` and `httpcore` are imported and undeclared |
| `test_every_runtime_dependency_is_used_or_allowlisted` | integration | Every declared runtime dependency is imported or allowlisted with a reason (`anyio`; `pydantic-settings`) | `markdownify` and `aiofiles` are declared and unused |
| `test_runtime_specifiers_are_exact_pins` | unit | Every runtime specifier is `==` | `pyjwt[crypto]>=2.13.0` is a range |
| `test_httpcore_network_backend_is_importable_and_declared` | integration | The private `httpcore._backends.base.NetworkBackend` stays importable with `connect_tcp`, and `httpcore` is declared | `httpcore` is undeclared |

Greened by: the `pyproject.toml`/`uv.lock` corrections. The `pydantic-settings`
allowlist entry is expected to be removed when the settings migration imports it;
that removal is that migration's change, not this one.

### Hook hardening — `tests/ci/test_pre_commit_hardening.py`, `tests/ci/test_hook_pins.py`

| Test | Layer | Pins | RED today |
| --- | --- | --- | --- |
| `test_pre_commit_hooks_are_enabled_for_large_files_and_private_keys` | unit | `check-added-large-files --maxkb=1024` and `detect-private-key` under the existing hooks entry | Neither hook is enabled |
| `test_gitleaks_hook_is_present_and_sha_pinned` | unit | A `gitleaks` repository entry with a 40-character SHA | No gitleaks entry |
| `test_every_non_local_rev_is_a_sha_with_a_version_comment` | unit | Every non-local hook `rev` is a 40-hex SHA carrying `# v<version>` | The configured revs are moving tags |
| `test_pin_tracking_repos_are_frozen_to_known_shas` | integration | The ruff and hooks repos are frozen to the known SHAs and comments | Both are tags |
| `test_rejects_a_non_sha_rev_on_a_non_local_repo` | unit | The hook-pin checker rejects a non-local repo whose `rev` is not a 40-hex SHA | The checker has no generic rule |
| `test_passes_when_rev_matches_pin` (fixtures reworked) | unit | The checker pairs a SHA `rev` with its `# v<version>` comment | It compares the raw scalar to the pin |
| `test_fails_on_mismatched_rev` (fixtures reworked) | unit | A comment-version mismatch is reported with the version | The comment is stripped before comparison |

Greened by: the hook config additions/freezing and the checker's generic rule
plus comment-based ruff pairing.

## RED inventory (as authored)

- **`tests/ci/test_codeql_workflow.py`** — 2 failures.
- **`tests/ci/test_makefile_targets.py`** — 3 failures.
- **`tests/ci/test_declared_dependencies.py`** — 3 failures.
- **`tests/ci/test_release_dist.py`** — 3 failures.
- **`tests/ci/test_in_image_test_lists.py`** — 5 failures (1 passing parameterised
  case of the pin test: the adversarial script is already in sync).
- **`tests/ci/test_httpcore_private_api.py`** — 1 failure.
- **`tests/ci/test_live_provider_http_status.py`** — 8 failures.
- **`tests/ci/test_pre_commit_hardening.py`** — 4 failures.
- **`tests/ci/test_integration_job_ran.py`** — 5 failures (new tests only).
- **`tests/ci/test_live_image_smoke.py`** — 1 failure (new test only).
- **`tests/ci/test_live_provider_matrix.py`** — 2 failures (new tests only).
- **`tests/ci/test_hook_pins.py`** — 4 failures (reworked fixtures plus the new
  rejection test).

Pre-existing tests in these files that continue to pass are regression guards,
not part of the RED inventory.

## Notes for the implementation waves

- `tests/` is owned by the test author. If a test is wrong, the orchestrator
  re-dispatches the test author; implementation waves must not edit tests.
- The `hermetic_integration` marker must be registered before the selector uses
  it, or the strict-markers addopts fail.
- Do not weaken trust-tier, sandbox or fail-closed behaviour to satisfy any
  test; the tests assert the stronger behaviour, not the weaker one.
