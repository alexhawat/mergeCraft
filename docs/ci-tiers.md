# CI tiers

mergeCraft splits CI into four tiers (#1493). Each job belongs to exactly one tier.

| Tier | Question | Representative jobs |
|------|----------|---------------------|
| 1 — Rules | Do edits follow repo rules? | `Verify (rules py3.14)` — `make lint`, `make typecheck`, `make lockcheck`; pre-commit hooks locally |
| 2 — This change | Does this PR work? | `Verify (tests …)`, `Verify (security audit …)`, `Verify (coverage gate py3.14)` on PRs; `mergecraft review` |
| 3 — Main works | Did the full suite pass before merge? | `Required integration`, `Build slim image`, `Action-image E2E`, image scans, `Eval gate`, boundary proofs — `merge_group` and non-PR `CI` runs |
| 4 — Release | Is this SHA releasable? | `release.yml` publish gate (requires tier 3 green on the SHA) |

## Job inventory (this repository)

| Job | Workflow | Tier | Notes |
|-----|----------|------|-------|
| `Verify (rules py3.14)` | `ci.yml` | 1 | Fail-fast; gates later jobs via `needs:` |
| `Verify (toolchain py*)` | `ci.yml` | 1–2 | Lockfile on PRs |
| `Verify (tests …)` | `ci.yml` | 2 | Change-scoped selection on PRs (`scripts/ci_select_tests.py`) |
| `Verify (coverage gate py3.14)` | `ci.yml` | 2 on PR / 3 on main | Publishes coverage artifact |
| `Verify (security audit …)` | `ci.yml` | 2 | gitleaks / trufflehog slice |
| `Verify (static + build …)` | `ci.yml` | 2 | Build + workflow lint after rules |
| `mergecraft review` | `mergecraft.yml` | 2 | Required on PRs |
| `Required integration` | `ci.yml` | 3 | Not on ordinary PR pushes |
| `Privileged boundary proofs` | `ci.yml` | 3 | Required when security surface changes on PR |
| `Build slim image` / E2E / scans | `ci.yml`, `e2e.yml` | 3 | Merge queue / main |
| `Eval gate` | `ci.yml` | 3 | Full replay |
| `Full verify` | `ci-cd.yml` | 3 | Main delivery |
| `Publish release` | `release.yml` | 4 | Tier 3 prerequisite |

## Agents and contributors

Before pushing from a cloud agent or locally, run:

```bash
make lint && make typecheck
uv run pre-commit run --all-files
```

On PRs, CI tier 1 (`Verify (rules py3.14)`) must pass before tier 2 jobs start.