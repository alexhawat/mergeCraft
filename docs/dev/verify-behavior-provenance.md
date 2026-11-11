# Behaviour verification: field provenance

Which GitHub issue asked for each field of the `mergecraft verify-behavior`
input and report. The consumer contract is in
[`docs/verify-behavior.md`](../verify-behavior.md).

**Audience:** contributor

## Field provenance

Which GitHub issue asked for each field. `#61` is canonical; `#62` and `#63`
are absorbed into the same contract.

### Input

| Field | Issues |
|-------|--------|
| `mode` | 61, 62, 63 |
| `repo_path` | 62, 63 |
| `startup_command` | 61, 62, 63 |
| `base` | 61 |
| `base_url` | 61, 62, 63 |
| `issue_or_pr` | 61, 62 |
| `acceptance_criteria` | 61, 62, 63 |
| `auth.strategy` | 62 |
| `credential_env_names` | 63 |
| `artifacts_dir` | 61, 62 |
| `viewport` | 63 |
| `device_targets` | 63 |
| `allowed_network` | 63 |
| `forbidden_network` | 63 |
| `prior_screenshots` | 63 |
| `repro_notes` | 63 |
| `yaml_input` | 62 |
| `actions` | click / fill / type steps (this CLI) |

### Output

| Field | Issues |
|-------|--------|
| `schema_version` | schema pin (this contract) |
| `mode` | 61, 62, 63 |
| `target` | 61, 62, 63 |
| `target_url` | 61, 62, 63 |
| `status` | 61, 62, 63 |
| `steps` | 61, 62, 63 |
| `acceptance_criteria` | 61, 62, 63 |
| `observed` | 61, 62, 63 |
| `expected` | 61, 62, 63 |
| `observed_mismatches` | 61, 62 |
| `skipped_or_unverified` | 61 |
| `artifacts.screenshots` | 61, 62, 63 |
| `artifacts.video` | 61, 62, 63 |
| `artifacts.trace` | 62, 63 |
| `artifacts.logs` | 61, 62, 63 |
| `artifacts.network_summary` | 63 |
| `console_errors` | 63 |
| `application_logs` | 63 |
| `suggested_next_fix` | 62, 63 |
| `blocked.missing` | 61, 62, 63 |
| `timestamp` | 62 |
| `credential_names` | credentials-by-name rule |
| `driver` | `cdp` / `stub` / unset — which driver produced the report; `--allow-stub` tries the browser first and falls back to the stub only when the stack is unavailable |
