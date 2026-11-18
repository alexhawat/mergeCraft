# CI tiers

mergeCraft sorts its CI jobs into four tiers (#1493). Each job below belongs to
exactly one tier. The tier says which question a job answers; the "Runs on"
column says where it runs today.

| Tier | Question | Where it runs |
|------|----------|---------------|
| 1 — Rules | Do the edits follow the repo's rules? | pre-commit locally, then the first PR job |
| 2 — This change | Does this change work? | every PR push |
| 3 — Main works | Is the whole product healthy with this change in? | every PR push, `merge_group`, and pushes to `main` |
| 4 — Release | Is this SHA releasable? | `release.yml` |

## Current state

- **Tier 1 is fail-fast.** `Verify (rules py3.14)` runs `make lint`,
  `make typecheck` and `make lockcheck`. The expensive jobs `needs:` it, so a
  lint error stops integration, the image build, the scans and the E2E from
  starting.
- **Tier 2 keeps the full unit lane on PRs.** Both py3.11 shards and the py3.14
  coverage gate run the whole unit suite on every code PR. `Changed tests
  (py3.11, fast feedback)` additionally runs just the tests that
  `scripts/ci_select_tests.py` maps from the changed paths, as an early signal.
  It is not a required check, and it does no work when the change cannot be
  narrowed (a dependency change, or nothing that maps to an existing test).
- **Tier 3 still runs on every code PR.** `ci.yml` listens for `merge_group`,
  but the repository has no merge queue yet, so nothing would run or require
  these jobs there. They stay on PRs, and stay required through
  `Verify (static + build …)`, until a merge queue requires them. Moving them
  off PRs is a follow-up that has to land together with the ruleset change.
- **Tier 4 is planned.** `release.yml` does not yet check that a SHA passed
  tier 3 before publishing.

## Job inventory: `ci.yml`

| Job | Tier | Runs on | Reason |
|-----|------|---------|--------|
| `Verify (rules py3.14)` | 1 | PR, merge group, push | Cheapest signal; gates the expensive jobs |
| `Verify (toolchain py*)` | 2 | PR, merge group, push | Lockfile and toolchain match on both Pythons |
| `Verify (tests …)` | 2 | PR, merge group, push | Full unit lane on py3.11 |
| `Changed tests (py3.11, fast feedback)` | 2 | PR | Early signal from the tests mapped to the changed paths; not required |
| `Verify (coverage gate py3.14)` | 2 | PR, merge group, push | Full unit suite plus coverage floors and patch coverage |
| `Verify (security audit …)` | 2 | PR, merge group, push | Secret and dependency scans |
| `Static checks (py*)` | 2 | PR, merge group, push | Build, docs and workflow lint |
| `Verify changed deployment candidates` | 2 | PR, merge group, push | Checks an `action.yml` image pin when one changes |
| `Privileged boundary proofs` | 2 | PR, merge group, push | Security-sensitive; must stay required on PRs |
| `Eval gate` | 2 | PR, merge group, push | Structural replay of the review evals for the change |
| `Eval rescore delta` | 2 | PR | Advisory; reviewer-surface comparison |
| `Shadow fixture replay` | 2 | PR, merge group, push | Advisory |
| `Verify (static + build …)` | 2 | PR, merge group, push | Final gate: fails unless every required job above and below succeeded |
| `Required integration (py*)` | 3 | PR, merge group, push | Keyless integration suite |
| `Build slim image (shared)` | 3 | PR, merge group, push | Image the scans and E2E consume |
| `Action-image E2E` | 3 | PR, merge group, push | End-to-end run of the built action image |
| `Image scan (slim)` / `Image scan (analyzers)` | 3 | PR, merge group, push | Blocking Trivy scans |
| `Verify (root container privilege py3.14)` | 3 | PR, merge group, push | Root-container proof against the built image |
| `Verify (mutation advisory py3.14)` | 3 | schedule | Nightly, non-blocking |

Docs-only PRs skip the work in the code-only jobs, and image-only PRs (a sole
`action.yml` image pin) skip everything but the deployment-candidate check; the
final gate knows which skips each of those allows.

The other workflows (`integration.yml`, `ci-matrix.yml`, `e2e.yml`,
`docker.yml`, `image-security.yml`, `codeql.yml`, `mergecraft.yml`,
`ci-cd.yml`, `release.yml`) are not inventoried here yet.

## Agents and contributors

Before pushing from a cloud agent or locally, run:

```bash
make lint && make typecheck
uv run pre-commit run --all-files
```

On PRs, tier 1 (`Verify (rules py3.14)`) must pass before the expensive jobs start.
