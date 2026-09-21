# Jev gate — judgment patterns

Design patterns for the pre-LLM screening gate in `src/mergecraft/jev/`. This
records the intended shapes for question packs, thresholds, and layering so they
are implemented deliberately rather than rediscovered.

These are mergeCraft-owned patterns with no external product dependency. The
gate ranks and filters units before (or alongside) the generative reviewer; it
does not replace any existing stage.

## Where this sits

```text
PR / local diff
  → analyzers (unchanged)
  → segment units
  → Jev screen + funnel        ← this document
  → policy: rank and annotate (shadow only — see below)
  → generative reviewer (always runs)
  → verifier on Critical/Major
  → publish
```

Unit segmentation is implemented in `jev/segment.py`; question construction in
`jev/questions.py`; scoring and routing policy in `jev/judge.py` and
`jev/policy.py`.

## 1. Dimension question pack

Screen each unit against a fixed set of dimensions using typed true/false (or
probability) questions. Each question states explicitly what to **inspect**,
what to **ignore**, and gives short true/false examples, so the model cannot
wander into style nits.

| Dimension | Question intent |
|-----------|-----------------|
| Correctness | Concrete path to a wrong runtime result from the unit |
| Security | Weakened authorization, injection, secrets, or trust boundary |
| Reliability | Crash, race, leak, deadlock, or poor recovery |
| Compatibility | Breaks a caller, format, protocol, or public behaviour |
| Test gap | Important changed behaviour lacks targeted test evidence |

## 2. Staged funnel

Orchestration stays in code; the model only answers narrow questions.

```text
screen all units (parallel, capped concurrency)
  → keep signals above the screen threshold
  → profile top units (category / review priority)
  → follow top signals: pick evidence region → classify mechanism → score severity
  → optional owner / specialist routing above the routing severity
  → blocking vs comment policy at the blocking severity
```

Starting knobs, to be tuned against adjudicated findings rather than left
provisional:

| Knob | Starting point | Role |
|------|----------------|------|
| Screen threshold | ~0.7 | Drop weak dimension hits before expensive follow-ups |
| Max follow-ups | ~8 | Cap locate/score calls per run |
| Max profiles | ~5 | Cap file/unit profiling |
| Concurrency | ~3 | Bound parallel gate calls |
| Min location confidence | ~0.55 | Reject weak evidence picks |
| Routing / blocking severity | mid / high on a 0–3 rubric | Specialist route vs request-changes |

These numbers are starting points, not measured values. See
[Calibration status](#calibration-status).

## 3. Mechanism classification after evidence pick

Once a region is selected, ask a choice over concrete mechanisms for that
dimension — condition/state/data-flow, authorization/injection,
cleanup/concurrency — always including an explicit **no-issue** option, so a
high screen probability can still die when the evidence does not support it.

Severity is a separate score on a small rubric, not free text.

## 4. Independent questions, not one multi-option bag

Run independent questions per unit and per dimension. Folding many units into a
single choice makes the options compete for probability mass and suppresses
multiple true positives.

## 5. Policy and thresholds live in code

Vocabulary (dimensions, mechanisms, owners, rubrics) and numeric gates belong in
a pure config/domain module. Workflow code only sequences calls and applies
those numbers. Findings stay structured until the existing publisher turns them
into comments or checks.

## 6. One-way layering

Keep a strict dependency direction so the gate stays testable and does not grow
upward imports:

```text
cli / Action entry → review workflow → adapters (git, files, store) → domain (config, types, patch)
```

An import-direction check in CI — no upward imports, no cycles between entry
surfaces — is worth adding if this grows.

## 7. Honest scope

The gate does **not** replace deterministic analyzers, generative review
comments, the Critical/Major verifier, or multi-language symbol extraction.

Findings from this stage are structured signals, not proof of a defect, until
analyzers or the verifier corroborate them.

## Current enforcement status

Nothing in this document describes a gate that can block or skip work today.

`predict_jev_action` in `jev/policy.py` returns `enforced=False` unconditionally,
and its docstring states that the reviewer is never skipped. The configured gate
mode (`shadow` or `enforce`) is recorded in the prediction's metadata but is not
acted on — setting `enforce` does not enforce.

So the thresholds above govern ranking and annotation only. Treat any suppression,
skip, or fail-closed behaviour as future work, and do not configure a repository on
the assumption that this stage withholds anything from the reviewer.

## Calibration status

The thresholds above are unmeasured starting points. Calibrating them requires
findings labelled independently of the system under test, and the existing
corpus is agent-seeded — calibrating against it would be circular.

Until an independently adjudicated corpus exists, treat every number here as
provisional and do not describe the gate as calibrated. See
[`eval-methodology.md`](eval-methodology.md) for corpus provenance and issue
#140 for published precision/recall reporting.
