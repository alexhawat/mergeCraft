# Operator action: land mergeCraft dogfood workflow on `main` (D6)

**Status:** Blocked on operator — W10 does **not** push this to `main`.

## Why a separate step

GitHub resolves `pull_request_target` workflows from the repository **default branch** (`main`), not from `pre-0.0.1`. Today `main` holds only `LICENSE`; Batch C worktrees target `pre-0.0.1`. Landing `.github/workflows/mergecraft.yml` on `main` is the first real content on the production default branch and must be an explicit operator decision (plan D6).

## Review artifact (Batch C PR)

| Item | Path |
|------|------|
| Rendered hardened workflow | [`dogfood-mergecraft.yml`](dogfood-mergecraft.yml) |
| Template source | `scripts/example_workflows/hardened.yml.tpl` + `scripts/render_example_workflows.py` |

Dogfood overrides baked into the artifact:

- **`branches`:** `[pre-0.0.1]` — PRs targeting the real trunk (see `.github/workflows/ci.yml`).
- **`CI_JOB_PREFIX`:** `"Verify ("` — matches CI job names: `Verify (toolchain)`, `Verify (tests N/2)`, `Verify (static + build)`, `Verify (security audit)`.
- **Action pin:** full SHA `f98aeb0063b387a51960503a758351608d377002` (`origin/pre-0.0.1` at sweep baseline). **Bump to the release SHA** you intend to run before merging to `main`.

## Operator checklist (separate PR → `main`)

1. **Branch:** Create a short-lived branch from `main` (e.g. `dogfood/mergecraft-workflow`).
2. **Copy workflow:** Move [`dogfood-mergecraft.yml`](dogfood-mergecraft.yml) to `.github/workflows/mergecraft.yml` on that branch (strip the review-only header comments if desired).
3. **Pin parity:** Update `action_pin_hardened` / the `uses:` SHA to the commit you want consumers (and this repo) to run; align with any Makefile or docs pins per README § Pin parity.
4. **Secrets:** Configure repository secrets on `alexhawat/mergeCraft`:
   - `CLAUDE_CODE_OAUTH_TOKEN` and/or `ANTHROPIC_API_KEY` (see README Authentication table).
5. **Optional ruleset:** If `mergeCraft review` is a required check, add a branch ruleset on `pre-0.0.1` requiring job `mergeCraft review` (and understand `neutral` / fail-open semantics from README).
6. **Open PR targeting `main`**, review, merge. The workflow takes effect on the **next** PR after merge (not the PR that introduces the file).
7. **Issue #9:** After merge, comment on #9 that dogfooding is live (or leave open if secrets/ruleset are still pending). Batch C Final (C.4) closes #9 only when this step is done.

## Regenerate after template changes

```bash
MERGECRAFT_EXAMPLE_BASE_BRANCHES='[pre-0.0.1]' \
MERGECRAFT_EXAMPLE_CI_JOB_PREFIX='Verify (' \
MERGECRAFT_EXAMPLE_ACTION_PIN_HARDENED='<full-commit-sha>' \
uv run python scripts/render_example_workflows.py --variant hardened
# Copy stdout or examples/workflows/mergecraft-hardened.yml with overrides applied to docs/artifacts/dogfood-mergecraft.yml
```

## Explicit non-actions (W10)

- Do **not** commit `.github/workflows/mergecraft.yml` on `pre-0.0.1` from the batch worktree unless the operator decides this repo should also run mergeCraft from the staging branch (inert under current default-branch policy).
