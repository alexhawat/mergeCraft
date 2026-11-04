# Blast-radius classifier

The blast-radius classifier turns repo-root-relative changed paths and optional diff statistics into a deterministic merge lane. It is a pure function: it does not read the repository, environment, or network.

## Lane semantics

- **Low** (`eligible`) — documentation, tests, generated output without another high-risk signal, and small isolated source changes. Required checks must still pass.
- **Medium** (`assisted`) — dependency changes, public API changes, broad reversible source changes, source changes without tests, and edits to the configuration that governs the review itself.
- **High** (`forbidden`) — migrations; authentication, security, permissions, or payment code; secrets, deployment, or production config; and irreversible infrastructure. A generated file is high only when another high-risk signal is also present.

The result also names the detected categories, the coded lane reasons, a checklist of gates, a human-readable reason, and the next required action. Classification does not itself enable automatic merge.

## Categories and defaults

| Category | Default lane |
|---|---|
| `migrations` | high |
| `auth_security_payment` | high |
| `secrets_config_deployment` | high |
| `irreversible_infra` | high |
| `review_config` | medium |
| `dependency_changes` | medium |
| `public_api_changes` | medium |
| `source_without_tests` | medium |
| `generated_files` | low; high only alongside another high-risk category |

`review_config` covers `.mergecraft/**` (except the run-state files `learnings.md`, `feedback.json`, `memory.json` and `analyzers.lock`) and analyzer or linter config such as `ruff.toml`, ESLint config, `.golangci.yml`, `.rubocop.yml`, `.semgrepignore`, `.gitleaks.toml`, `.gitleaksignore`, `.bandit`, `setup.cfg`, `tsconfig.json` and `.pre-commit-config.yaml`. A PR that can reduce the scrutiny applied to itself never lands in the `eligible` lane.

Path matching is supplemented by small diff-text heuristics for destructive database or infrastructure operations and synthetic secret-assignment markers.

## Lane reasons

Every classification carries `reasons`: one row per signal, each with a stable dotted `code`, the `lane` that reason forces, and a `message`. The lane is the highest lane over the reasons, and there is always at least one. The table lists each code with its default lane. A reason's emitted lane differs from the default only through a repository override or the small-isolated-source carve-out, and the message says which.

| Code | Default lane | When |
|---|---|---|
| `signal.missing.paths` | medium | `changed_paths` is absent, empty or not a list |
| `signal.missing.diff` | medium | `diff_stats` is absent or not a mapping |
| `paths.migrations` | high | a changed path is under a `migration` or `migrations` directory |
| `paths.auth` | high | a changed path is under an `auth` directory |
| `paths.security` | high | a changed path is under a `security` directory |
| `paths.payment` | high | a changed path is under a `payment`, `payments` or `billing` directory |
| `paths.permissions` | high | a changed path is under a `permission` or `permissions` directory |
| `paths.secrets_config` | high | a path under `config/`, or `.env.example`, changed |
| `paths.deployment` | high | a GitHub Actions workflow under `.github/workflows/` changed |
| `paths.irreversible_infra` | high | a path under `infra/terraform/` changed |
| `diff.destructive_sql` | high | the diff text contains `DROP TABLE`, `ALTER TABLE` or `CREATE TABLE` |
| `diff.secret_assignment` | high | the diff text contains a secret-assignment marker such as `password =` or `aws_secret_access_key` |
| `diff.irreversible_command` | high | the diff text contains `rm -rf` or `terraform destroy` |
| `paths.public_api` | medium | a package `__init__.py` changed |
| `deps.changed` | medium | a dependency manifest or lockfile changed (`pyproject.toml`, `uv.lock`, `package.json`, `go.mod` and similar) |
| `tests.missing` | medium | a `src/` path that is not generated output changed and no test path changed, whatever generated paths sit beside it; emitted at low, with the carve-out named, when the carve-out applies |
| `paths.review_config` | medium | config that governs how the PR is reviewed changed; an override cannot lower it |
| `source.changed` | medium | a `src/` path that is not generated output changed, whatever generated paths sit beside it; a change made only of generated paths emits `paths.generated` instead |
| `paths.generated` | low | a changed path is under a `generated` directory |
| `source.small_isolated` | low | the carve-out applies: one `src/` file, at most 5 changed lines, no review config, no `source_without_tests` override, no high reason |
| `baseline.clean` | low | no other reason was emitted |

The rendered `reason` string starts with the codes (`Lane reasons: deps.changed, source.changed.`) and keeps the category sentence, so existing readers keep working. The run record prints the lane and the codes on one line.

The small-isolated-source carve-out lowers only `tests.missing` and replaces `source.changed` with `source.small_isolated`. Any other reason keeps its lane, so a tiny edit to a package `__init__.py` stays `medium`.

## Checklist

Every classification also carries `checklist`: one row per gate, always in this order, with `passed` set to `true`, `false` or `null`.

| Gate | Reasons that fail it | Reads |
|---|---|---|
| `inputs` | `signal.missing.paths`, `signal.missing.diff` | both inputs |
| `migrations` | `paths.migrations`, `diff.destructive_sql` | paths and `diff_stats` |
| `auth_security_payment` | `paths.auth`, `paths.security`, `paths.payment`, `paths.permissions` | paths |
| `secrets_config_deployment` | `paths.secrets_config`, `paths.deployment`, `diff.secret_assignment` | paths and `diff_stats` |
| `irreversible_infra` | `paths.irreversible_infra`, `diff.irreversible_command` | paths and `diff_stats` |
| `public_api` | `paths.public_api` | paths |
| `dependencies` | `deps.changed` | paths |
| `tests` | `tests.missing` | paths and `diff_stats` |
| `review_config` | `paths.review_config` | paths |
| `source` | `source.changed`, and `paths.generated` when an override raises it | paths and `diff_stats` |

A gate that reads `diff_stats` counts it as measured whenever the mapping is present, even when it carries no diff-text key. The production packet always puts the diff text in it, beside the line counts.

- `true`: the gate's inputs were all given and none of its reasons forces the lane above `low`. A reason lowered to `low` by an override or the carve-out passes its gate.
- `false`: one of its reasons forces the lane above `low`. A failure measured from one input stays `false` even when the other input is missing.
- `null`: not measured. Without `changed_paths` every gate except `inputs` is `null` unless a reason already failed it. Without `diff_stats`, `migrations`, `secrets_config_deployment`, `irreversible_infra`, `tests` and `source` are `null` unless a path already failed them. `inputs` is `false` whenever either input is missing.

`auto_merge_lane` is `eligible` exactly when every gate is `true`, which is exactly when the lane is `low`. A single `false` or `null` keeps the result out of `eligible`: unknown is never green.

## Missing inputs escalate

Unknown is never green. A classification that was not given what it measures cannot vouch for a `low` lane:

| Missing input | Category | Lane |
|---|---|---|
| `changed_paths` absent or empty | `signal_missing` | at least medium (`assisted`) |
| `diff_stats` absent | `signal_missing` | at least medium (`assisted`) |

Each missing input also emits its own reason, `signal.missing.paths` or `signal.missing.diff`, at `medium`, and fails the `inputs` gate. Neither is a `RuleSet` key, so no repository override can lower it, and the small-isolated-source carve-out cannot either. The rendered reason names the missing input, for example `Missing classifier input: changed_paths, diff_stats.` A higher lane from another reason still wins.

The approval gate and the risk-band ordering follow the same rule:

- Both gate rows that map to `auto_merge` require evidence that the classification had inputs: a non-empty `files_changed` on the packet, no `signal_missing` category, and, when the packet carries a checklist, an `inputs` gate that is `true`. `low_risk_passing` also requires a `low` lane. `clean_pass` covers every lane that is not `forbidden`, including `medium`, so without this check it would auto-merge a `signal_missing` packet. A packet that claims a lane with nothing measured falls through to `needs_human_review`.
- `risk_at_or_above` ranks an unrecognised risk band above `critical`, so a misspelt or unknown band meets every threshold instead of reading as `low`.

## Per-repository overrides

`classify_blast_radius(change, rule_set=...)` accepts an additive `RuleSet`. Each supplied category's `lane` replaces the shipped default for the reasons in that category, and the reason's message says so, for example `(lane medium → low by repository override)`. The catalogue default never changes. Omitting `rule_set`, or passing an empty one, uses the defaults unchanged.

Two floors cannot be lowered. `review_config` may be raised but never set below `medium`: a PR that edits the config governing its own review is never `eligible`. `signal.missing.*` has no `RuleSet` key. A `source_without_tests` override also turns off the small-isolated-source carve-out.

The repository-settings field that supplies this value is part of the separate lane-policy wiring wave. The classifier does not read settings itself.

## Merge Evidence Packet

`BlastRadiusClassification` is the typed value of `MergeEvidencePacket.blast_radius`; see [`evidence-packet.md`](evidence-packet.md) for its wire shape. `reasons` and `checklist` arrived with packet schema `1.18.0`; a packet written earlier carries neither, and the approval gate falls back to the category check for it.
