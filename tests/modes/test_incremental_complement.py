"""Incremental complement lens routing (RC9, W5 metadata) — W6.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W6).
Pins ``route_lenses_complement`` in ``review/lens_routing.py`` and prior-round
dispatched-lens metadata from ``modes/_pr_summary_format.py``.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""

_LENS_CATALOG_YAML = """
agents:
  lens-security:
    role: reviewer
    lens: security
    triggers:
      categories: [auth_security_payment]
  lens-migration:
    role: reviewer
    lens: schema-migration
    triggers:
      categories: [migrations]
  lens-performance:
    role: reviewer
    lens: performance
    triggers:
      categories: [source_without_tests]
  lens-impact:
    role: reviewer
    lens: impact
    triggers:
      categories: [public_api_changes]
  lens-copy:
    role: reviewer
    lens: copy-vs-code
    triggers:
      categories: [public_api_changes]
  lens-data:
    role: reviewer
    lens: data-integrity
    triggers:
      categories: [migrations]
  lens-correctness:
    role: reviewer
    lens: correctness
    triggers:
      categories: [source_without_tests]
  lens-integration:
    role: reviewer
    lens: integration
    triggers:
      categories: [dependency_changes]
  lens-holistic:
    role: reviewer
    lens: holistic
    triggers:
      minRiskBand: medium
  lens-research:
    role: reviewer
    lens: research-validated-assumptions
    triggers:
      minRiskBand: medium
  lens-operational:
    role: reviewer
    lens: operational-readiness
    triggers:
      minRiskBand: high
  lens-test-integrity:
    role: reviewer
    lens: test-integrity
    triggers:
      categories: [source_without_tests]
"""


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _change(*paths: str, **signals: object) -> dict[str, object]:
    return {"changed_paths": list(paths), "diff_stats": signals}


def _routing_mod() -> Any:
    try:
        return importlib.import_module("mergecraft.review.lens_routing")
    except ImportError as err:
        pytest.fail(f"lens routing import failed: {err}")


def _pr_summary_mod() -> Any:
    return importlib.import_module("mergecraft.modes._pr_summary_format")


def _classify_change(change: dict[str, object]) -> Any:
    from mergecraft.classify.change_classifier import classify_change

    return classify_change(change)


def _load_routing_registry(tmp_path: Path) -> Any:
    routing = _routing_mod()
    settings = load_repo_settings(root=tmp_path)
    return routing.load_routing_registry(settings=settings, repo_root=tmp_path)


def _prior_dispatched_from_review_body(body: str) -> tuple[str, ...]:
    pr_summary = _pr_summary_mod()
    return pr_summary.parse_dispatched_lenses_from_review_body(body)


def test_lenses_that_did_not_run_last_round_are_preferred(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    routing = _routing_mod()
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)

    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change(
            "migrations/20260816_add_status.sql",
            "src/mergecraft/__init__.py",
            "pyproject.toml",
            files_changed=4,
            diff="ALTER TABLE invoices ADD COLUMN status text;",
        )
    )
    prior_dispatched = ("security", "schema-migration")
    baseline = routing.route_lenses(classification, registry=registry)

    complement = routing.route_lenses_complement(
        classification,
        registry=registry,
        prior_dispatched_lens_ids=prior_dispatched,
        dispatch_budget=8,
    )

    assert complement.selected_lens_ids
    complement_new = [
        lens_id for lens_id in complement.selected_lens_ids if lens_id not in prior_dispatched
    ]
    assert complement_new, "complement routing must prefer lenses that did not run last round"
    assert set(complement.selected_lens_ids) != set(baseline.selected_lens_ids)


def test_complement_routing_does_not_rerun_every_lens_every_round(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    routing = _routing_mod()
    pr_summary = _pr_summary_mod()
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)

    registry = _load_routing_registry(tmp_path)
    catalog_lens_ids = {binding.lens for binding in registry.iter_lens_bindings()}
    classification = _classify_change(
        _change(
            "migrations/20260816_add_status.sql",
            "src/mergecraft/__init__.py",
            "pyproject.toml",
            files_changed=4,
            diff="ALTER TABLE invoices ADD COLUMN status text;",
        )
    )
    prior_dispatched = ("security", "schema-migration", "performance")
    prior_body = pr_summary.merge_dispatched_lenses_into_review_metadata(
        "**Reviewed changes** — prior round.\n\n<!--\nmergeCraft review metadata\n-->\n",
        dispatched_lens_ids=prior_dispatched,
    )
    restored_prior = _prior_dispatched_from_review_body(prior_body)
    assert restored_prior == prior_dispatched

    complement = routing.route_lenses_complement(
        classification,
        registry=registry,
        prior_dispatched_lens_ids=restored_prior,
        dispatch_budget=8,
    )

    assert len(complement.selected_lens_ids) <= 8
    assert len(complement.selected_lens_ids) < len(catalog_lens_ids)
