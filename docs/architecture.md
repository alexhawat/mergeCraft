# Architecture overview

How a review run moves from a pull request event to a verdict, and which part of `src/mergecraft/` does each step.

**Audience:** contributor (maintainers and integrators)

This is a map, not a specification. Each stage links to the page that owns the
detail; the pipeline picture in the [README](../README.md#how-it-works) shows
the same flow without the code. Package names below are the directories under
`src/mergecraft/`, and the stage order follows `main()` in
`src/mergecraft/main.py`.

## One run, end to end

```text
event  ->  setup  ->  trust tier  ->  analyzers  ->  triage / skip gates
       ->  review agent(s)  ->  verifier  ->  typed findings
       ->  structural verdict  ->  publish (comments, checks, evidence packet)
```

| Stage | What happens | Where it lives |
|-------|--------------|----------------|
| Entry | The Docker Action starts `mergecraft.main`; the CLI's `mergecraft review` runs the same pipeline offline against a local diff and never posts to GitHub. | `action/`, `main.py`, `cli/`, `offline_review.py` |
| Setup | Resolve the event payload, load settings, resolve credentials, assemble the model chain, build the tool context, check out the pull request, run the optional setup script. | `main.py` (`_setup_run`, `_resolve_credentials`, `_assemble_model_chain`), `config/`, `workflow/`, `prep/` |
| [Trust tier](glossary.md#trust-tier) | Classify the run from the event and the code it would check out: a same-repository pull request is trusted; a fork or `pull_request_target` run is not. The tier decides secrets, tools and which analyzers may run. | `analyzers/trust.py` (`derive_trust_tier`), `config/trust_policy.py`; see [workflows](workflows.md#security-model) and [trust policy](trust-policy.md) |
| Gates | Skip when every changed file is ignored, and decide whether the change needs a full review at all. | `main.py` (`_ignore_paths_gate`, `_triage_gate`, `_reapproval_gate`), `reapproval.py` |
| [Analyzers](glossary.md#analyzer) | Run the deterministic tools that match the languages and trust tier, and normalize their output to findings. | `analyzers/` (manifests, registry, execution, SARIF); catalog in [ANALYZERS](ANALYZERS.md) |
| Context | Build the repository map and retrieval context, classify the change, and compute the [blast radius](glossary.md#blast-radius). | `context/`, `classify/`, `requirements/`, `xrepo/` |
| Review agent | The model, run by a [harness](glossary.md#harness), reads the diff with a set of [lenses](glossary.md#lens) and records a verdict and findings through typed tools. Extra reviewers on the [roster](glossary.md#roster) run in their own dispatches. | `agents/`, `review/` (engine, lens routing, file-group fan-out), `modes/`, `mcp/`; see [agent roster](agent-roster.md) |
| [Verifier](glossary.md#verifier) | A read-only second pass re-reads Critical and Major findings before publication. | `agents/verifier.py`; the optional Jev screening gate in `jev/` runs before the reviewer ([Jev gate patterns](jev-gate-patterns.md)); [REVIEW-DOCTRINE](REVIEW-DOCTRINE.md) |
| [Typed findings](glossary.md#typed-finding) | One schema for analyzer and model findings: severity, location, evidence, scope. | `findings/`, `evidence/`, `review_taxonomy.py` |
| Verdict | `mergecraft-approval` is a pure function of typed findings, run state and trust tier, never of prose. | `agents/gates.py` (`decide_approval`), `review_checks.py`, `run_outcome.py`; [REVIEW-CHECKS](REVIEW-CHECKS.md) |
| Publish | Inline comments, the `mergecraft` and `mergecraft-approval` checks, optional SARIF upload, the run record, and the [evidence packet](glossary.md#evidence-packet). | `main.py` (`_publish`, `_finalize`), `scm/`, `pr/`, `evidence/`, `analyzers/sarif_upload.py` |

## Supporting packages

| Package | Role |
|---------|------|
| `config/` | Settings schema (`RepoSettings` and friends), precedence layers, trust policy. Security and runtime blocks reject unknown keys ([config failure policy](config-failure-policy.md)). |
| `policy/`, `review_policy/` | Policy-as-code rules, scoping and enforcement ([policy evidence](policy-evidence.md)). |
| `memory/`, `evals/` | [Learnings](glossary.md#learnings), review memory, and the file-backed eval bank ([eval bank](eval-bank.md)). |
| `tracing/` | Optional span export to JSONL, Logfire or OTLP ([tracing](TRACING.md)). |
| `security/`, `reliability/`, `enterprise/` | Network-boundary and publication surfaces, redacted diagnostic bundles, self-hosted controls. |
| `mcp/`, `capabilities/` | The review-only tool surface shared by the public stdio MCP server and the reviewer's in-run MCP tools ([MCP](mcp.md)). |
| `verify/`, `browser/` | Behaviour verification ([verify-behavior](verify-behavior.md)). |
| `cli/` | The Typer command tree; the generated reference is [cli](cli.md), and exit codes are in [EXIT-CODES](EXIT-CODES.md). |

## Boundaries that matter

- **Pull-request-controlled input is data.** `.mergecraft/config.yaml` and the
  analyzer configuration that a pull request changes do not apply to that
  pull request's own review; trust-sensitive settings are read from the base
  ([agent roster](agent-roster.md#trust-boundary), [REVIEW-CHECKS](REVIEW-CHECKS.md)).
- **Authority is separate from execution.** A model's `approve` is a record,
  not a publication; the run decides what to publish from typed findings.
- **Findings carry a scope.** `change` findings can block; `run` findings
  describe how the review executed and are advisory ([REVIEW-DOCTRINE](REVIEW-DOCTRINE.md)).

## See also

- [Review doctrine](REVIEW-DOCTRINE.md)
- [Evidence packet](evidence-packet.md)
- [Threat model](THREAT-MODEL.md)
- [Contributing: analyzers](CONTRIBUTING-ANALYZERS.md)
- [Cost](cost.md)
