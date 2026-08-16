"""AP5 lens catalog suite — promote 20 themed lenses from prose to registry (AP5.1 RED).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP5).
Covers bundled lens modules under ``mergecraft.agents.lenses``, registry merge,
``mergecraft lens list|show|test``, Review.py de-duplication, and routing recall
against the eval-shaped baseline. Implementation lands in AP5.2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.mcp.shared import ToolClass
from mergecraft.modes.Review import TEMPLATE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

pytestmark = pytest.mark.xfail(reason="AP5.2", strict=True)

_FIXTURES = Path(__file__).resolve().parent.parent / "_fixtures"
_RECALL_BASELINE = _FIXTURES / "ap5_routing_recall_baseline.json"

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""

# D11 — thirteen starter-menu lenses from Review.py (display title → registry id).
_PROMPT_LENS_TITLES: dict[str, str] = {
    "correctness": "correctness & invariants",
    "data-integrity": "data integrity & atomicity",
    "impact": "impact",
    "copy-vs-code": "copy vs code",
    "research-validated-assumptions": "research-validated assumptions",
    "security": "security",
    "privilege-drop-ordering": "privilege drop ordering",
    "user-journey": "user-journey",
    "operational-readiness": "operational readiness",
    "integration": "integration & cross-cutting",
    "test-integrity": "test integrity",
    "performance": "performance",
    "holistic": "holistic",
}

# Seven backlog lenses that ship alongside the starter menu (not prose-duplicated).
_BACKLOG_LENS_IDS: tuple[str, ...] = (
    "api-compatibility",
    "concurrency",
    "schema-migration",
    "dependency-build",
    "policy",
    "requirements",
    "cross-repo",
)

_STARTER_MENU_BULLETS: tuple[str, ...] = tuple(
    f"**{title}**" for title in _PROMPT_LENS_TITLES.values()
)

_runner = CliRunner()


def _write_config(tmp_path: Path, body: str = _DEFAULT_MODELS_YAML) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _load_lens_catalog() -> Any:
    from mergecraft.agents.lenses import load_lens_catalog

    return load_lens_catalog()


def _get_lens(lens_id: str) -> Any:
    from mergecraft.agents.lenses import get_lens

    return get_lens(lens_id)


def _load_default_registry(tmp_path: Path) -> Any:
    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def _build_subsystem_lens(lens_id: str) -> Any:
    from mergecraft.agents.lenses import build_subsystem_lens

    return build_subsystem_lens(lens_id)


def _starter_menu_rubric(display_title: str) -> str:
    """Extract the preserved rubric prose for one starter-menu lens from Review.py."""
    marker = f"**{display_title}**"
    start = TEMPLATE.find(marker)
    if start < 0:
        msg = f"starter-menu lens {display_title!r} not found in Review.py TEMPLATE"
        raise AssertionError(msg)
    dash = TEMPLATE.find(" — ", start)
    if dash < 0:
        msg = f"no rubric delimiter for lens {display_title!r}"
        raise AssertionError(msg)
    end = TEMPLATE.find("\n   - **", dash)
    if end < 0:
        end = len(TEMPLATE)
    return TEMPLATE[dash + 3 : end].strip()


def test_all_thirteen_prompt_lenses_have_registry_entries(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D11 — every starter-menu lens is a bundled registry binding."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    catalog = _load_lens_catalog()
    registry = _load_default_registry(tmp_path)
    registry_lens_ids = {binding.lens for binding in registry.iter_lens_bindings()}

    prompt_ids = set(_PROMPT_LENS_TITLES)
    assert catalog.prompt_lens_ids == prompt_ids
    for lens_id in _PROMPT_LENS_TITLES:
        assert lens_id in registry_lens_ids, f"missing registry entry for {lens_id!r}"
        binding = next(item for item in registry.iter_lens_bindings() if item.lens == lens_id)
        assert binding.triggers is not None, f"{lens_id} must declare routing triggers"


def test_seven_backlog_lenses_have_entries(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Backlog lenses ship as bundled registry entries alongside the starter menu."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    catalog = _load_lens_catalog()
    registry = _load_default_registry(tmp_path)
    registry_lens_ids = {binding.lens for binding in registry.iter_lens_bindings()}

    assert catalog.backlog_lens_ids == set(_BACKLOG_LENS_IDS)
    for lens_id in _BACKLOG_LENS_IDS:
        assert lens_id in registry_lens_ids, f"missing backlog lens {lens_id!r}"


def test_subsystem_lenses_need_no_entry() -> None:
    """Orchestrator-invented subsystem lenses inherit discovery shape without catalog rows."""
    catalog = _load_lens_catalog()
    assert "auth" not in catalog.all_lens_ids

    subsystem = _build_subsystem_lens("auth")
    assert subsystem.lens_id == "auth"
    assert subsystem.rubric.strip()
    assert subsystem.triggers is not None
    assert subsystem.required_evidence


def test_each_lens_declares_triggers_rubric_and_required_evidence() -> None:
    """Every bundled lens exposes triggers, rubric prose, and required evidence."""
    catalog = _load_lens_catalog()

    for lens_id in sorted(catalog.all_lens_ids):
        lens = _get_lens(lens_id)
        assert lens.lens_id == lens_id
        assert lens.triggers is not None, f"{lens_id} missing triggers"
        assert lens.rubric.strip(), f"{lens_id} missing rubric"
        assert lens.required_evidence, f"{lens_id} missing required_evidence"


def test_each_lens_has_its_own_toolset(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Lens toolsets differ by intent — security sees analyzers; copy-vs-code sees read/grep."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    security = _get_lens("security")
    copy_lens = _get_lens("copy-vs-code")

    assert security.tool_classes != copy_lens.tool_classes
    assert ToolClass.ANALYSIS in security.tool_classes
    assert ToolClass.REPOSITORY_READ in copy_lens.tool_classes
    assert ToolClass.ANALYSIS not in copy_lens.tool_classes


def test_lens_rubric_text_is_preserved_from_the_prompt() -> None:
    """Bundled rubric text must byte-match the extracted Review.py starter-menu prose."""
    for lens_id, display_title in _PROMPT_LENS_TITLES.items():
        expected = _starter_menu_rubric(display_title)
        lens = _get_lens(lens_id)
        assert lens.rubric == expected, f"rubric drift for {lens_id!r}"


def test_prompt_no_longer_duplicates_the_menu() -> None:
    """Review.py must reference the lens registry instead of duplicating starter-menu bullets."""
    assert "lens catalog" in TEMPLATE.lower() or "load_lens_catalog" in TEMPLATE
    for bullet in _STARTER_MENU_BULLETS:
        assert bullet not in TEMPLATE, f"duplicate starter-menu bullet still in Review.py: {bullet}"


def test_lens_test_verb_runs_one_lens_in_isolation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``mergecraft lens test`` runs one bundled lens against a diff fixture."""
    diff_path = tmp_path / "security.patch"
    diff_path.write_text(
        "diff --git a/src/auth/session.py b/src/auth/session.py\n"
        "@@ -1,3 +1,4 @@\n"
        "+def validate(token):\n"
        '+    return db.query(f"SELECT 1 FROM sessions WHERE token = {token}")\n',
        encoding="utf-8",
    )
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = _runner.invoke(app, ["lens", "test", "security", "--diff", str(diff_path)])

    assert result.exit_code == 0, result.stdout + result.stderr
    output = result.stdout.lower()
    assert "security" in output
    assert "rubric" in output or "hypothesis" in output


def test_review_coverage_does_not_regress(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Eval-shaped routing recall must not drop versus the frozen baseline fixture."""
    from mergecraft.classify.change_classifier import classify_change
    from mergecraft.review.lens_routing import route_lenses

    baseline = json.loads(_RECALL_BASELINE.read_text(encoding="utf-8"))
    min_recall = float(baseline["min_recall"])
    cases: list[dict[str, object]] = baseline["cases"]

    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    registry = _load_default_registry(tmp_path)

    recalls: list[float] = []
    for case in cases:
        change = {
            "changed_paths": case["changed_paths"],
            "diff_stats": case["diff_stats"],
        }
        expected = set(case["expected_lens_ids"])
        classification = classify_change(change)
        decision = route_lenses(classification, registry=registry)
        selected = set(decision.selected_lens_ids)

        if not expected:
            assert selected == set(), f"{case['id']}: trivial case must route zero lenses"
            recalls.append(1.0)
            continue

        hit = len(expected & selected) / len(expected)
        recalls.append(hit)
        assert expected.issubset(selected), (
            f"{case['id']}: expected {sorted(expected)}, got {sorted(selected)}"
        )

    mean_recall = sum(recalls) / len(recalls)
    assert mean_recall >= min_recall, (
        f"routing recall regressed: {mean_recall:.3f} < baseline {min_recall:.3f}"
    )
