# Cost

Where the cost of a review comes from, and which settings change it.

**Audience:** consumer (product and setup documentation)

mergeCraft is MIT-licensed and has no hosted service, so there is no mergeCraft
fee. A review spends two things you already pay for: your model provider
([BYOK](glossary.md#byok)) and the GitHub Actions run that hosts the Action.
This page does not quote per-review prices for either. The repository documents
no per-review token count or price for the general case, and the amount depends
on your provider, model, plan and the size of the change.

## What a review spends

| Stage | Spends model tokens? |
|-------|----------------------|
| [Analyzers](glossary.md#analyzer) (actionlint, zizmor, ShellCheck and others) | No. They are deterministic tools. |
| Review agent reading the diff | Yes. This is the main cost. |
| [Verifier](glossary.md#verifier) re-reading Critical and Major findings | Yes, only for those findings. |
| Extra reviewers on the [roster](glossary.md#roster) | Yes. Each configured reviewer is its own provider dispatch. |
| File-group fan-out (opt-in) | Yes. Each group is a full provider dispatch, so six groups cost roughly six extra reviewer runs ([agent roster](agent-roster.md)). |
| Jev screening (opt-in) | Calls a hosted service rather than your model provider; see [Jev gate patterns](jev-gate-patterns.md#data-sent-to-typesafe). |

The cost and tokens mergeCraft reports for a run, and the run budget it charges
(`runBounds.tokenBudget`, `runBounds.costBudgetUsd`), include every dispatch —
the primary reviewer, the verifier, each extra roster reviewer and each
file-group reviewer — not only the primary reviewer.

## Levers you control

- **Subscription or API key.** A Claude Pro/Max or ChatGPT login is billed under
  that plan rather than per token; an API key is metered by the provider
  ([authentication](authentication.md)).
- **Model choice and fallbacks.** `models:` is an ordered chain. A later model
  runs only when an earlier one has no credential or fails with a retryable
  error, so a backup is a cost only when it is used
  ([chain semantics](authentication.md#chain-semantics--model)).
- **Fewer reviewers.** Each extra reviewer on the roster adds a dispatch.
  `mergecraft provider status` shows what CI will run.
- **Less diff.** The `ignore_paths` Action input and `review.ignorePaths`
  keep changelogs, lockfiles and minified files out of what the
  reviewer reads; several of those are ignored by default
  ([workflows](workflows.md#ignoring-paths)).
- **A run cap.** The Action `timeout` input bounds run duration (default 1h)
  ([action reference](action-reference.md)).
- **Token band.** `runBounds.tokenBudget` (default 2M) is an advisory target.
  `tokenBudgetTolerance` (default 10%) defines a hard ceiling for streaming
  reviewers. OpenCode (and other NDJSON stream drivers) charge each provider
  step against that ceiling while the review runs, stop the model before
  further spend when a step would exceed it, and fold only any remaining usage
  delta at dispatch finalize. Crossing the target alone does not invalidate a
  completed review (#1477); crossing the ceiling during dispatch ends the
  attempt with `inconclusive` and names the budget in the run output.
- **Preview before spending.** `mergecraft plan` prints the model chain,
  toolset, analyzers and a token estimate without any provider call, and
  `mergecraft review --dry-run` prints the review prompt without calling a
  model.

## Review budget trends

Set any of `review.budget.target.tokensP50`, `costUsdP50`, and `wallSecondsP50`
in the pull request's base-side config to monitor usage across reviews. The
Action compares each configured target with the corresponding median and shows
the p50, p90 and number of measurements in the step summary when a target is
exceeded. `review.budget.windowSize` defaults to 20. Lower it for a window that
responds faster to changes in spend. The trend warning has no effect on a
review's verdict or per-run token ceiling.

The window includes the current full review and the newest attributable
mergeCraft records from GitHub pull request reviews in the same repository.
Historical records require a reviewer App or PAT with an identifiable author.
The search inspects at most 50 recently updated pull requests, 100 reviews per
pull request and publisher, and the 200 newest candidate bodies. The summary
shows the actual sample count and whether a read limit was reached. When
history is unavailable the Action can still report the current measurement.
Missing measurements, including incomplete recorded costs, are omitted from
that metric's percentiles. Review wall time covers setup and agent execution.
Historical costs and times use the precision of the published records.

On trusted same-repository runs with an attributable publisher and
`issues: write`, mergeCraft maintains a tracking issue per metric using
`mergecraft-budget-trend` labels. It updates the existing issue during a breach
and closes it when measurements return within target.

## Provider-specific figures in this repository

These are the only prices the repository records. They are the providers'
published rates as of the date shown, not a mergeCraft price list.

- **OpenCode Go** — per-million-token rates for two DeepSeek models, the
  time-of-day multiplier, the plan fees, and how mergeCraft reports a cost
  estimate versus provider-reported cost: [OpenCode Go review
  costs](opencode.md#opencode-go-review-costs). mergeCraft does not allocate
  plan fees per review, and the provider console is authoritative for charges.
- **Ultramarine 1 Flash** (Paper Instruments) — the posted review's Cost line is
  priced from token usage at the rates listed in
  [Ultramarine as a second reviewer](ultramarine-second-reviewer.md).

## See also

- [Authentication](authentication.md)
- [Agent roster](agent-roster.md)
- [Architecture](architecture.md)
- [Glossary](glossary.md)
