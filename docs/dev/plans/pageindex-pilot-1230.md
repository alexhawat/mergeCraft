# PageIndex retrieval pilot — issue #1230

## Decision and boundary

**Decision: do not integrate PageIndex into review execution from this PR.** Evaluate it as an offline retrieval aid first. Issue #1230 explicitly requires any review-flow integration to be proposed in a separate PR, and retrieval output must not silently become policy authority.

This PR adds no PageIndex dependency, API key, Cloud/MCP endpoint, workflow step, network call, or review-prompt injection. It does not change what mergeCraft sends to reviewers.

## Candidate corpus

| Source | Format | Role in the pilot |
|---|---|---|
| `docs/jev-architecture-checklist.md` | Markdown | Primary index target; numbered maintainer checklist used at Jev call sites |
| `docs/jev-gate-patterns.md` | Markdown | Companion explanation of the staged funnel, code-owned policy, and calibration limits |
| `src/mergecraft/jev/architecture.py` | Python | Source-of-truth cross-check for question construction, state filtering, and routing |
| `src/mergecraft/jev/pack_registry.py` | Python | Source-of-truth cross-check for versioned pack metadata and thresholds |

The eleven-item architecture checklist is the initial corpus because sections are independently addressable and linked to the Jev implementation. Start with the Markdown text layer; do not add PDF/OCR or Cloud dependencies until a concrete source-format gap is demonstrated.

## Prototype protocol

For each of at least three real PRs that touch Jev call sites, pack definitions, routing, or the architecture docs:

1. Supply only the PR title, description, and changed paths as the retrieval query context.
2. Retrieve the top relevant checklist/design sections from the fixed checkout snapshot.
3. Record source path, heading/numbered item, retrieved snippet, and the PR change that makes it relevant.
4. Open the source section and verify the citation manually. A missing, fabricated, or unsupported citation is a failed result.
5. Record irrelevant sections and unsupported claims as noise; do not let retrieved text change review policy.

Use these three query templates across the selected PRs:

- **Question packs / routing:** Which checklist rules govern fan-out of speculative questions, independent answers, model pinning, and usage logging? Expected anchors: checklist items 1, 2, and 5.
- **Trust boundary / state:** Which rules govern state filtering and nonce-fencing of untrusted contributor-controlled strings? Expected anchors: checklist items 3 and 10.
- **Judgment / policy boundary:** Which rules keep confidence separate from permission and keep arithmetic/side effects in code? Expected anchors: checklist items 7 and 9, plus the corresponding gate-pattern sections.

## Manual result ledger

| Real PR | Query template | Relevant section retrieved? | Citation resolves and supports claim? | Noise / unsupported text | Human notes |
|---|---|---|---|---|---|
| PR 1 — select a Jev call-site change | Question packs / routing | pending | pending | pending | pending |
| PR 2 — select a trust-boundary change | Trust boundary / state | pending | pending | pending | pending |
| PR 3 — select a policy/routing change | Judgment / policy boundary | pending | pending | pending | pending |

**Execution status: not run.** No PageIndex SDK or PageIndex-backed retrieval session was available while preparing this change, and no retrieval quality, citation accuracy, latency, or cost measurements are claimed. The ledger must be completed from actual runs against three real PRs before a go/no-go decision; this document is a reproducible protocol, not a passing evaluation result.

## Integration options and measurement

Evaluate in this order:

1. **Local/offline SDK:** preferred first path for repository Markdown and text-layer documents. Capture model/provider token usage and end-to-end latency for each PR query.
2. **Separate review-skill PR:** only if the local results show repeatable value. It must return source-grounded snippets and stable section references; a reviewer must verify each citation before relying on it.
3. **Cloud/MCP:** consider only if the local path cannot handle an identified format or workflow requirement. Keep credentials in an environment/secret store; never commit or log `PAGEINDEX_API_KEY`.

The vendor pricing figures referenced in the issue are not measured pilot costs. Record actual provider/model, input/output token use, elapsed indexing and retrieval time, and any Cloud charges before comparing local and hosted options.

## Go/no-go criteria

A separate integration proposal needs all of the following: three real-PR ledgers completed; relevant sections retrieved for each; citations resolving to the checked-in source and supporting the retrieved claim; noise/hallucination notes; measured latency and cost; and explicit maintainer approval.

Until those gates pass, keep PageIndex as a manual experiment and keep all review decisions and policy enforcement in existing deterministic/code-owned paths.
