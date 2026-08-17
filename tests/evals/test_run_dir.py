"""#219 — the raw-findings run directory must tolerate ``/`` in model slugs.

RED suite for PR EV1 (sub-wave EV1.1; implementation EV1.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

``run_live_detection`` builds its run id as ``f"{provider}-{model}-{stamp}-{suffix}"``
and joins it onto ``results_dir / "raw-findings"`` — a routed model slug such as
``openrouter/openai/gpt-5`` therefore *splits the run directory into nested
directories* (#219), so the published evidence path no longer names one flat run
directory per run. EV1.2 sanitizes the slug so the run dir is always exactly one
path component under ``raw-findings/``.

The contract is pinned **behaviourally** through ``run_live_detection`` — no new
symbol is named here, so EV1.2 may place the sanitizing helper anywhere on the
path (a ``sanitize_run_id_component``-style helper in ``evals/live_run.py`` is
the plan's sketch, not a pinned name).

Keyless and deterministic: findings come from an injected stub ``review_fn``
(the B3 dependency-injection seam), so no live gate is required and
``skipped: no live gate`` does not apply to this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.evals.live_run import (
    BASELINE_FILENAME,
    DetectionCase,
    discover_detection_cases,
    run_live_detection,
)

_XFAIL_EV1_2 = pytest.mark.xfail(
    reason="green after EV1.2: slug sanitization for the raw-findings run dir (#219)",
    strict=False,
)


# ── fixtures (mirrors tests/evals/test_live_run.py's detection-corpus helpers) ──


def _write_detection_case(corpus_dir: Path, case_id: str) -> None:
    """One closed-world, zero-issue detection case — enough to drive a run dir."""
    case_dir = corpus_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "task.patch").write_text(
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    (case_dir / BASELINE_FILENAME).write_text(
        json.dumps({"closed_world": True, "issues": []}),
        encoding="utf-8",
    )


def _stub_review_fn() -> Any:
    """A keyless ``review_fn`` that reports zero findings for every case."""

    def _fn(_case: DetectionCase) -> list[dict[str, Any]]:
        return []

    return _fn


# ── #219: slash-bearing slugs ──


@_XFAIL_EV1_2
def test_model_slug_with_slash_does_not_split_the_run_dir(tmp_path: Path) -> None:
    """A routed slug (``openrouter/openai/gpt-5``) yields exactly one directory
    directly under ``raw-findings/`` — never a ``provider/model`` nesting."""
    corpus = tmp_path / "corpus"
    _write_detection_case(corpus, "bench-detect-clean-001")
    case = discover_detection_cases(corpus)[0]
    results_dir = tmp_path / "results"

    metrics = run_live_detection(
        [case],
        provider="openrouter",
        model="openrouter/openai/gpt-5",
        review_fn=_stub_review_fn(),
        results_dir=results_dir,
    )

    raw_dir = Path(metrics.raw_findings_dir)
    rel = raw_dir.relative_to(results_dir / "raw-findings")
    assert rel.parts == (raw_dir.name,), (
        f"run dir must be a single path component under raw-findings/, got {rel}"
    )
    assert raw_dir.is_dir()
    # Sanitized, not truncated: every slug segment survives in the run-dir name,
    # so two different routed models can never collapse into one directory.
    for segment in ("openrouter", "openai", "gpt-5"):
        assert segment in raw_dir.name


@_XFAIL_EV1_2
def test_run_dir_is_stable_across_providers(tmp_path: Path) -> None:
    """The run-dir naming convention is one flat component for *every* provider —
    the shape must not change just because one provider routes its slugs — and
    distinct runs still land in distinct directories (collision resistance)."""
    corpus = tmp_path / "corpus"
    _write_detection_case(corpus, "bench-detect-clean-001")
    case = discover_detection_cases(corpus)[0]
    results_dir = tmp_path / "results"

    provider_models = (
        ("claude", "claude-sonnet-5"),
        ("openai", "gpt-5"),
        ("openrouter", "openrouter/openai/gpt-5"),
    )
    run_dir_names: list[str] = []
    for provider, model in provider_models:
        metrics = run_live_detection(
            [case],
            provider=provider,
            model=model,
            review_fn=_stub_review_fn(),
            results_dir=results_dir,
        )
        raw_dir = Path(metrics.raw_findings_dir)
        assert raw_dir.parent == results_dir / "raw-findings", (
            f"{provider}/{model}: run dir must sit directly under raw-findings/"
        )
        run_dir_names.append(raw_dir.name)

    assert len(set(run_dir_names)) == len(run_dir_names)
