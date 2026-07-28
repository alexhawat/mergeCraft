# Analyzer platform — test plan (W1 RED)

Wave plan: `.ignorelocal/waves/mergecraft-analyzer-platform-wave-plan.md`
Worktree: `mergecraft-analyzer-platform` @ `wave/analyzer-platform`

## xfail schedule

| Wave | Test files | Marker reason prefix |
|------|------------|----------------------|
| **W2** | `tests/analyzers/test_manifest.py`, `test_registry.py`, `test_finding.py`, `test_resolve.py`, `tests/config/test_settings.py` (extensions), `tests/test_review_taxonomy.py` (`FINDING_CONFIDENCES`) | `green after W2:` |
| **W3** | `tests/analyzers/test_provision.py`, `test_trust.py`, `test_sandbox.py` | `green after W3:` |
| **W4** | `tests/analyzers/parsers/test_sarif.py`, `test_native.py`, `tests/analyzers/test_redaction.py` | `green after W4:` |
| **W5** | `tests/analyzers/test_scope.py`, `test_cluster.py`, `tests/analyzers/test_budget.py` (budget half) | `green after W5:` |
| **W6** | `tests/analyzers/test_adapters_github.py`; keeps `test_redaction.py` parametrisation green | `green after W6:` |
| **W7** | `tests/mcp/test_analyzers.py`, `tests/agents/test_verifier.py`, `tests/test_review_taxonomy.py` (prompt half), `test_budget.py` (placement half) | `green after W7:` |

All cross-wave markers use `strict=False` (repo `xfail_strict = true`).

## Finding field table (D2)

| Field | Type / constraint | Test coverage |
|-------|-------------------|---------------|
| `tool` | str | `test_finding.py`, adapter tests |
| `rule_id` | str | parsers, adapters |
| `category` | `review_taxonomy.FINDING_CATEGORIES` | `test_finding.py` |
| `severity` | `review_taxonomy.FINDING_SEVERITIES` | `test_finding.py`, SARIF mapping |
| `confidence` | `certain` \| `likely` \| `possible` | `test_finding.py`, `test_review_taxonomy.py`, cluster |
| `message` | str | parsers, scope, cluster |
| `path` | repo-relative str | scope, adapters |
| `start_line` / `end_line` | int | scope, parsers |
| `fingerprint` | delegates to `finding_fingerprint()` | `test_finding.py`, `test_cluster.py` |
| `evidence` | list | `test_cluster.py` |
| `remediation` / `autofix` | optional | finding construction |
| `introduced_by_pr` | `true` \| `false` \| `unknown` | `test_scope.py` |
| `source` | `analyzer` \| `agent` \| `ci` | `test_finding.py`, budget |
| `cluster_id` | optional str | cluster tests |

## Trust-tier matrix (D7)

| Event / setting | Expected tier | Tests |
|-----------------|---------------|-------|
| W0.4 same-repo `pull_request`, `fork=false` | `trusted` | `test_trust.py::test_same_repo_pull_request_is_trusted`, probe shape test |
| Fork `pull_request` (`head.repo.fork=true`) | `untrusted` | `test_trust.py::test_fork_pull_request_is_untrusted` |
| `shell: disabled` | analyzers surface off | `test_trust.py`, `test_analyzers.py` |
| Manifest `trust: trusted` on untrusted run | skipped + reason | `test_trust.py` |
| W0.4 missing net ns / tmpfs / ro bind | skip with named reason | `test_sandbox.py` |

## Planted finding → wave map (W0.8 fixture repo)

| Planted finding | Path | Wave | Test |
|-----------------|------|------|------|
| Broken workflow | `.github/workflows/broken.yml` | W6 actionlint | `test_adapters_github.py` |
| Unpinned action `@main` | `.github/workflows/unpinned-action.yml` | W6 zizmor | `test_adapters_github.py` |
| Unquoted shell variable | `scripts/deploy.sh` | W6 ShellCheck | `test_adapters_github.py` |
| `FROM …:latest` | `Dockerfile` | W6 Hadolint | `test_adapters_github.py` |
| Canary fake secret | `.env.example` | W4/W6+ D8 | `test_redaction.py` (parametrised) |
| Vulnerable dependency | `requirements.txt` | Catalog C2 | fixture README only |
| Unsafe SQL migration | `db/migrations/001_add_users.sql` | Catalog C4 | unplanted guard in adapters |
| OpenAPI breaking change | `openapi/v1.yaml` | Catalog C4 | unplanted guard |
| MCP exfil manifest | `.mergecraft/mcp-servers/evil-server.yaml` | Catalog C5 | unplanted guard |

## Contract matrix

| Decision | Unit | Integration | Functional | Primary tests |
|----------|------|-------------|------------|---------------|
| **D1** manifest | schema validation | catalog round-trip | — | `test_manifest.py` |
| **D2** Finding | taxonomy constraints | fingerprint delegation | — | `test_finding.py`, `test_review_taxonomy.py` |
| **D3** SARIF / native | parser fixtures | ingest → Finding | export round-trip | `parsers/test_sarif.py`, `test_native.py` |
| **D4** execution modes | preference order | resolve chain | — | `test_resolve.py` |
| **D5** no substitution | version note | repo-native wins | — | `test_resolve.py` |
| **D6** scoping | hunk filter | `introduced_by_pr` | — | `test_scope.py` |
| **D7** trust | tier derivation | env strip, skip trusted-only | MCP withhold | `test_trust.py`, `test_sandbox.py`, `test_analyzers.py` |
| **D8** redaction | value redaction | fingerprint/cache safe | — | `test_redaction.py` |
| **D10** pinned fetch | checksum fail | — | — | `test_provision.py` |
| **D11** verification | severity gate | withdrawn write | — | `test_verifier.py` |
| **D12** cluster | key derivation | multi-tool merge | — | `test_cluster.py` |
| **D13** exclusive_group | — | default enablement | — | `test_registry.py` |
| **D14** budget | cap = 8 | overflow mechanical | agent wins ties | `test_budget.py` |
| **D24** lockfile | entry schema | reproducible resolve | — | `test_provision.py` |
| Config `analyzers:` | parse/merge | unknown id warning | — | `test_settings.py` |
| W6 adapters | — | planted hits | no false positives | `test_adapters_github.py` |
| W7 MCP | `ran:false` contract | per-analyzer status | tool registration | `test_analyzers.py` |

## Inline budget constant

**D14 cap:** `8` (= floor(median agent inline 16 / 2) from W0.2). Asserted in `tests/analyzers/conftest.py` as `INLINE_BUDGET` and `test_budget.py`.

## Notes

- Lazy `importlib.import_module` in analyzer tests keeps collection clean before W2 creates `src/mergecraft/analyzers/`.
- Parser and adapter tests use recorded fixtures under `tests/analyzers/fixtures/`; no subprocess shell-out in parser tests.
