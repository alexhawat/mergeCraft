# Self-review and Action pin maintenance

How mergeCraft reviews its own pull requests, and how the Action pin that
workflow uses is kept current. This is maintainer material for this repository.
Consumers wiring mergeCraft into their own repositories want
[workflows](../workflows.md), [authentication](../authentication.md) and
[trust policy](../trust-policy.md) instead.

**Audience:** contributor

## Action pin

This repository's `.github/workflows/mergecraft.yml` records the review Action SHA
in a single workflow-level variable, the canonical ref:

```yaml
env:
  MERGECRAFT_ACTION_SHA: "<40-char-sha>"
```

`uses:` accepts no expressions, so each of the three review rungs
(`uses: alexhawat/mergeCraft@…`) carries the literal SHA with a
`# env.MERGECRAFT_ACTION_SHA` comment suffix. Nothing interpolates the variable.
A bump rewrites the variable and every literal together
(`scripts/bump_action_pin.py`), and two targets compare each literal against
the variable (`scripts/check_action_pin_freshness.py`):

| Target | Rules | Where it runs |
| --- | --- | --- |
| `make action-pin-check` | rungs disagree, a rung drifts from `env.MERGECRAFT_ACTION_SHA`, the pin diverges from the default branch's | `make ci-static` — a required PR check |
| `make action-pin-staleness-check` | all of the above, plus the pin lagging the default branch's own tip by more than `MERGECRAFT_MAX_ACTION_PIN_PRODUCT_LAG` non-merge commits under `src/mergecraft/` | `.github/workflows/action-pin-staleness.yml`, on every push to `main`, with a daily cron backstop |

The split is deliberate. Staleness compares `main`'s pin against `main`'s tip,
so nothing in it reads the pull request under review. While it gated PRs, one
stale pin on `main` failed every open PR at once — and the only change that
could clear it (repointing the pin at a manifest commit that does not exist
until the manifest PR merges) was blocked by that same red check (#669).

`action-pin-staleness.yml` files a single tracking issue instead, keeps it
current, and closes it once the pin is bumped. It measures on every push to
`main`, so debt is reported when it lands rather than up to a day later. The
daily cron is the backstop for a pin that goes stale because `main` moved under
it — GitHub's scheduler is best-effort, routinely late and skipped under load,
so it is the safety net rather than the primary trigger.

`make action-pin-check` still runs every rule a branch can actually act on.

Locally, plain `make action-pin-check` is the PR-scoped set; run
`make action-pin-staleness-check` for the full picture.

## Self-review App token and approval lifecycle

Each OpenCode Go, Codex or Claude attempt mints its own repository-scoped App token
when both App secrets are configured and the review is for the same repository.
A failed mint preserves the existing job-token review path. Per-attempt minting
avoids reusing a one-hour token throughout the 95-minute fallback cascade.
Tokens have real post-job revocation through the pinned official token action.

This repository has no separate App approval workflow. Self-review publishes a
COMMENT review and the `mergecraft review` status check; that check is the merge
gate, and code-owner review stays a human decision. The reviewer can publish
reviews and checks, so COMMENT-only configuration and check provenance are not an
independent approval boundary.

**Gate provenance.** The approval gate trusts **this run's own evidence-packet
verdict** — the review job exposes the final `decision.verdict` (`success` /
`failure` / `neutral`) as a job output, read through `needs.review.outputs.*`, or
reads `steps.mergecraft.outputs.evidence_packet` directly when the gate is a step
in the same job. Another workflow run cannot write those outputs, including one
added on the PR's own branch. A `mergecraft-approval` check only **corroborates**
that verdict: it must be issued on the reviewed head SHA by `github-actions` (or
by the configured App ID when `EXPECTED_APP_ID` is set) with
`external_id == "<run_id>:<run_attempt>"`, and its conclusion must equal the
output verdict. A missing or empty verdict, a conclusion that disagrees, or a
check that cannot be attributed to this run all fail closed with a named reason;
the only thing that passes is output `success` plus a corroborating check.

The structural check also carries `external_id=<run ID>:<run attempt>`.
The approval gate requires that exact attempt identity, so an older image
that does not emit it cannot pass the gate. Deploy the updated image and
workflow together; a matching run URL alone is insufficient after a rerun.

## Codex login write-back

A ChatGPT-subscription login (`CODEX_AUTH_JSON`) rotates its refresh token on
use. This repository's self-review writes the refreshed login back to the
`CODEX_AUTH_JSON` secret after every Codex run. The write-back is a workflow
step, not something the Action does: the Codex rung exports the refreshed
`auth.json` (the driver copies it to `MERGECRAFT_CODEX_AUTH_EXPORT` only when
the refresh token changed) and a post-step stores it with
`gh secret set CODEX_AUTH_JSON` under a token minted with only `secrets: write`.

| Token role | Repository scope | Installation permissions |
|------------|------------------|--------------------------|
| `CODEX_AUTH_JSON` write-back | Current repository only | `secrets: write` |

**Operator step:** grant the reviewer App the *Secrets: Read and write*
repository permission and accept the permission update on the installation.
Until then the mint fails and the write-back is skipped with a notice, leaving
the secret as it was.

## Dogfood posture

The committed [`.mergecraft/config.yaml`](../../.mergecraft/config.yaml) runs
this repository's own self-review at:

| Knob | Level | Effect on this repo |
|------|-------|---------------------|
| `trust.selfReview` | `full` | Execution and authority trust are both trusted on same-repo `pull_request_target` PRs, so trusted-tier analyzers run and the run's own verdict could unlock approval semantics |
| `prApproveEnabled` | `false` | The switch that keeps publication at COMMENT. Enabling it with `selfReview: full` would let the agent's own terminal verdict post APPROVE; this repository does not enable it |
| `trust.agentSandbox` | `same-repo` | `MERGECRAFT_CODEX_SANDBOX=danger-full-access` is honoured on any non-fork head |

Those knobs are read from the base-branch config snapshot at run start, so a
self-review PR cannot enable them until the config lands on the default branch.
`trust.sandboxTrustedAuthors` is not set in this repository's committed config.
The levels themselves are documented in [trust policy](../trust-policy.md).
