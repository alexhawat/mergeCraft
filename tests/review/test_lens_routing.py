"""AP4 lens routing suite — risk-based registry selection (AP4.1 RED).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP4).
Covers ``mergecraft.review.lens_routing`` — intersect classifier output with
each lens's declared trigger signals, record selected/skipped reasons, and
honour convention 6 (no fixed specialist cap). Implementation lands in AP4.2.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def _load_routing_registry(tmp_path: Path) -> Any:
    from mergecraft.review.lens_routing import load_routing_registry

    settings = load_repo_settings(root=tmp_path)
    return load_routing_registry(settings=settings, repo_root=tmp_path)


def _classify_change(change: dict[str, object]) -> Any:
    from mergecraft.classify.change_classifier import classify_change

    return classify_change(change)


def _route_lenses(classification: Any, registry: Any) -> Any:
    from mergecraft.review.lens_routing import route_lenses

    return route_lenses(classification, registry=registry)


def test_routing_selects_from_the_registry(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Selected lens ids must come from registry lens bindings only."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change(
            "src/billing/refunds.py",
            files_changed=1,
            lines_added=4,
            lines_deleted=1,
        )
    )

    decision = _route_lenses(classification, registry)
    registry_lens_ids = {binding.lens for binding in registry.iter_lens_bindings()}

    assert decision.selected_lens_ids, "billing change must route at least one lens"
    assert set(decision.selected_lens_ids).issubset(registry_lens_ids)


def test_trivial_change_routes_zero_lenses(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Genuinely trivial doc typo changes skip all specialist lenses."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change("docs/guide.md", files_changed=1, lines_added=1, lines_deleted=1)
    )

    assert classification.is_trivial is True
    decision = _route_lenses(classification, registry)
    assert decision.selected_lens_ids == ()


def test_one_line_billing_change_is_not_trivial(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """One-line billing edits must not be skipped by a file-count heuristic."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change(
            "src/billing/tax_rate.py",
            files_changed=1,
            lines_added=1,
            lines_deleted=1,
            diff="@@ -1 +1 @@\n-OLD_RATE = 0.05\n+OLD_RATE = 0.06",
        )
    )

    assert classification.is_trivial is False
    decision = _route_lenses(classification, registry)
    assert len(decision.selected_lens_ids) >= 1


def test_migration_diff_routes_the_migration_lens(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Schema migration diffs must route the migration lens from the registry."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change(
            "migrations/20260816_add_status.sql",
            files_changed=1,
            diff="ALTER TABLE invoices ADD COLUMN status text;",
        )
    )

    decision = _route_lenses(classification, registry)
    assert "schema-migration" in decision.selected_lens_ids


def test_no_fixed_cap_on_lens_count(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Convention 6 — routing selects every matching lens; no fixed specialist cap."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change(
            "migrations/20260816_add_status.sql",
            "src/mergecraft/__init__.py",
            "pyproject.toml",
            "src/mergecraft/cli/app.py",
            files_changed=4,
            diff="ALTER TABLE invoices ADD COLUMN status text;",
        )
    )

    decision = _route_lenses(classification, registry)
    assert len(decision.selected_lens_ids) >= 9, (
        "high-signal change must not be capped to a small fixed lens count"
    )


def test_routing_decision_is_recorded_with_its_reason(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every lens gets a recorded selected/skipped decision with a reason."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML + _LENS_CATALOG_YAML)
    monkeypatch.chdir(tmp_path)
    registry = _load_routing_registry(tmp_path)
    classification = _classify_change(
        _change(
            "src/billing/tax_rate.py",
            files_changed=1,
            lines_added=2,
            lines_deleted=1,
        )
    )

    decision = _route_lenses(classification, registry)
    catalog_ids = {binding.lens for binding in registry.iter_lens_bindings()}
    recorded = {entry.lens_id: entry for entry in decision.entries}

    assert catalog_ids == set(recorded.keys())
    for entry in decision.entries:
        assert entry.reason.strip(), f"{entry.lens_id} must record a routing reason"
        assert entry.selected is (entry.lens_id in decision.selected_lens_ids)

    skipped = [entry for entry in decision.entries if not entry.selected]
    assert skipped, "skipped lenses must be recorded with reasons"
