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
- **Preview before spending.** `mergecraft plan` prints the model chain,
  toolset, analyzers and a token estimate without any provider call, and
  `mergecraft review --dry-run` prints the review prompt without calling a
  model.

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
