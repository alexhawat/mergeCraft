# Jev architecture checklist

Maintainer reference for TypeSafe System One / Jev call sites under
`src/mergecraft/jev/`. Implementation helpers live in
[`architecture.py`](../src/mergecraft/jev/architecture.py) and the versioned
pack registry in [`pack_registry.py`](../src/mergecraft/jev/pack_registry.py).

See also [`jev-gate-patterns.md`](jev-gate-patterns.md) for funnel design and
calibration status.

## Patterns (apply at every call site)

1. **Fan-out questions, route in code** — One `system_one` call carries every
   question you might need, including speculative asks (`build_system_one_questions`).
   Route on answers in Python; ignore unused speculative answers.

2. **Pin model + log** — `PINNED_MODEL` (`jev-1.13.0`) only; never floating
   aliases. Every successful call logs `model`, `input_tokens`, and
   `output_tokens` (plus GenAI trace spans when a tracer is bound).

3. **Filter state in code first** — `filter_state_for_pack` keeps only the
   fields listed in `pack_registry.PACK_REGISTRY`. Prefer evidence over summaries.

4. **Confidence is a second axis** — `route_choice` requires both the selected
   option and `confidence >= floor`. Stakes map to floors: read-only ~0.5,
   routing ~0.6, escalate ~0.9. `route_noul` uses the same inclusive-lower rule.

5. **Parallel questions are independent** — No cross-question dependencies inside
   one call. Need a prior answer or new tool result → a second request.

6. **Rebuild Choice menus from live catalogs** — `lens_pack()` reads
   `LENS_DEFINITIONS` at runtime; do not copy lens names into a static list.

7. **Confidence ≠ permission / ≠ outcome** — Side effects (skip reviewer,
   suppress, block merge) are decided in code. High confidence never skips the
   generative reviewer in this plan.

8. **Noul 0.5 = coin flip** — `NOUL_ACT_FLOOR` (0.5) is an act threshold, not
   a medium-intensity label. Do not port thresholds between noul and choice.

9. **Arithmetic/dates/counts in code** — Jev answers judgment questions only;
   counting and scoring stay in Python.

10. **Untrusted state fail-closed** — On `trust_tier="untrusted"`, string state
    fields are nonce-fenced via `render_untrusted` before dispatch. Injected
    instructions in PR/diff text are treated as hostile data.

11. **Version questions + thresholds together** — Edit pack metadata in
    `pack_registry.py` (state fields, threshold keys, corpus ids). Question
    copy stays in `questions.py` factories keyed by the same `pack_id`.

## Jaggedness constraints

TypeSafe/Jev models are **jagged**: strong on narrow judgment questions, weak on
multi-step reasoning, arithmetic, and long-context recall. Design call sites
accordingly:

- Keep each question narrow with explicit inspect/ignore criteria.
- Batch independent questions; never chain dependent asks in one call.
- Never trust a single high-confidence answer for irreversible side effects.
- Prefer deterministic code for gates; use Jev for ranking and annotation until
  an independently adjudicated corpus exists (see `jev-gate-patterns.md`).

Tests: `tests/jev/test_architecture.py` (routing, filtering, logging) and the
existing Jev suite under `tests/jev/`.
