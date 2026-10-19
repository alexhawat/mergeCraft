# Blast-radius classifier

The blast-radius classifier turns repo-root-relative changed paths and optional diff statistics into a deterministic merge lane. It is a pure function: it does not read the repository, environment, or network.

## Lane semantics

- **Low** (`eligible`) — documentation, tests, generated output without another high-risk signal, and small isolated source changes. Required checks must still pass.
- **Medium** (`assisted`) — dependency changes, public API changes, broad reversible source changes, source changes without tests, and edits to the configuration that governs the review itself.
- **High** (`forbidden`) — migrations; authentication, security, permissions, or payment code; secrets, deployment, or production config; and irreversible infrastructure. A generated file is high only when another high-risk signal is also present.

The result also names the detected categories, a human-readable reason, and the next required action. Classification does not itself enable automatic merge.

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

## Per-repository overrides

`classify_blast_radius(change, rule_set=...)` accepts an additive `RuleSet`. Each supplied category is merged over the shipped default, and the repository value wins for that category. Omitting `rule_set`, or passing an empty one, uses the defaults unchanged.

The repository-settings field that supplies this value is part of the separate lane-policy wiring wave. The classifier does not read settings itself.

## Merge Evidence Packet

`BlastRadiusClassification` is the typed value intended for `MergeEvidencePacket.blast_radius`. The separate lane-policy wiring wave owns populating that field and updating the packet schema version; this classifier only produces the deterministic value.
