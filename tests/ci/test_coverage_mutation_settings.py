"""C0 config surface — ciEvidence artifacts, coverage/mutation blocks, FindingSource."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, get_args

import pytest
from pydantic import ValidationError

from mergecraft.ci.coverage import complexity_from_source
from mergecraft.ci.crap import crap_score
from mergecraft.review_taxonomy import FindingSource
from tests.ci.support_crap import (
    C_D10_NOT_PROOF,
    C_D10_WEAK_TEST,
    DEFAULT_BANDS,
    DEFAULT_MAX_MUTANTS,
    DEFAULT_SURVIVOR_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
    REPO_ROOT,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_finding_source_is_unchanged_by_this_plan() -> None:
    """C-D3: ingested → ci, local → analyzer. No new literal."""
    assert get_args(FindingSource) == (
        "analyzer",
        "agent",
        "ci",
        "trajectory",
        "classifier",
    )


def test_docs_state_what_green_does_not_prove() -> None:
    """C-D10: a surviving mutant is evidence; zero survivors is not proof."""
    text = (REPO_ROOT / "docs" / "test-plans" / "crap-mutation-evidence.md").read_text(
        encoding="utf-8"
    )
    assert C_D10_WEAK_TEST in text
    assert C_D10_NOT_PROOF in text


def test_default_coverage_artifacts_empty_and_mode_shadow() -> None:
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    assert settings.ci_evidence.coverage_artifacts == []
    assert settings.coverage.mode == "shadow"
    assert settings.coverage.bands.watch == DEFAULT_BANDS["watch"]
    assert settings.coverage.bands.elevated == DEFAULT_BANDS["elevated"]
    assert settings.coverage.bands.crap == DEFAULT_BANDS["crap"]
    assert settings.coverage.bands.severe == DEFAULT_BANDS["severe"]


def test_default_mutation_artifacts_empty_mode_shadow_threshold_zero() -> None:
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    assert settings.ci_evidence.mutation_artifacts == []
    assert settings.mutation.mode == "shadow"
    assert settings.mutation.survivor_threshold == DEFAULT_SURVIVOR_THRESHOLD


def test_default_cli_bounds() -> None:
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    assert settings.mutation.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert settings.mutation.max_mutants == DEFAULT_MAX_MUTANTS
    assert settings.mutation.path_allowlist == []
    assert settings.coverage.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_absent_config_file_still_has_empty_coverage_artifacts(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    settings = load_repo_settings(tmp_path / "missing.yaml", load_learnings_files=False)
    assert settings.ci_evidence.coverage_artifacts == []
    assert settings.coverage.mode == "shadow"


def test_consumer_coverage_yaml_overrides_default_bands(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "push: restricted\n"
        "shell: restricted\n"
        "ciEvidence:\n"
        "  coverageArtifacts:\n"
        "    - coverage-json\n"
        "coverage:\n"
        "  mode: shadow\n"
        "  bands:\n"
        "    watch: 3\n"
        "    elevated: 15\n"
        "    crap: 30\n"
        "    severe: 50\n",
        encoding="utf-8",
    )
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings.ci_evidence.coverage_artifacts == ["coverage-json"]
    assert settings.coverage.bands.watch == 3
    assert settings.coverage.mode == "shadow"


def test_consumer_mutation_yaml_overrides_survivor_threshold(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "push: restricted\n"
        "shell: restricted\n"
        "ciEvidence:\n"
        "  mutationArtifacts:\n"
        "    - mutmut-json\n"
        "mutation:\n"
        "  mode: shadow\n"
        "  survivorThreshold: 2\n",
        encoding="utf-8",
    )
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings.ci_evidence.mutation_artifacts == ["mutmut-json"]
    assert settings.mutation.survivor_threshold == 2


def test_unknown_coverage_key_is_rejected(tmp_path: Path) -> None:
    from mergecraft.config.settings import load_repo_settings

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "push: restricted\nshell: restricted\ncoverage:\n  unknownKey: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_repo_settings(root=tmp_path, load_learnings_files=False)


def test_c2_c4_deliverable_symbol_export() -> None:
    """Direct name pins for C2-C4 deliverable types (verifier check 3)."""
    from mergecraft.ci.changed_functions import ChangedFunction
    from mergecraft.ci.coverage import (
        CoverageFunction,
        CoverageIngestResult,
        ParsedCoverage,
        complexity_from_source,
        coverage_inputs_from_context,
    )
    from mergecraft.ci.crap import CrapBands
    from mergecraft.ci.local_evidence import LocalEvidenceResult
    from mergecraft.ci.mutation import MutationIngestResult, MutationSurvivor, ParsedMutation
    from mergecraft.config.settings import (
        CoverageBandSettings,
        CoverageSettings,
        MutationSettings,
    )
    from mergecraft.mcp.context import ToolContext

    assert CrapBands.__name__ == "CrapBands"
    assert ChangedFunction.__name__ == "ChangedFunction"
    assert CoverageSettings.__name__ == "CoverageSettings"
    assert CoverageBandSettings.__name__ == "CoverageBandSettings"
    assert CoverageFunction.__name__ == "CoverageFunction"
    assert ParsedCoverage.__name__ == "ParsedCoverage"
    assert CoverageIngestResult.__name__ == "CoverageIngestResult"
    assert callable(complexity_from_source)
    assert callable(coverage_inputs_from_context)
    assert "ci_coverage_artifacts" in ToolContext.__dataclass_fields__
    assert MutationSurvivor.__name__ == "MutationSurvivor"
    assert ParsedMutation.__name__ == "ParsedMutation"
    assert MutationIngestResult.__name__ == "MutationIngestResult"
    assert MutationSettings.__name__ == "MutationSettings"
    assert "ci_mutation_artifacts" in ToolContext.__dataclass_fields__
    assert LocalEvidenceResult.__name__ == "LocalEvidenceResult"


# N3 — `complexity_from_source` weights CRAP, and nothing asserted its integer.
# Each source defines exactly one function starting on line 1; expected values
# are hand-computed as ``1 + decision nodes`` where the decision nodes are
# ``_DECISION_NODES`` in ``mergecraft.ci.coverage`` (If / For / AsyncFor /
# While / ExceptHandler / Assert / IfExp). Note that Boolean operators and
# comprehension ``if`` clauses are *not* decision nodes in this counter, so
# those fixtures stay at 1.
_COMPLEXITY_FIXTURES: Final[tuple[tuple[str, str, int], ...]] = (
    ("straight_line", "def straight_line(value):\n    return value\n", 1),
    ("single_if", "def single_if(value):\n    if value:\n        return 1\n    return 0\n", 2),
    (
        "if_elif_else",
        "def if_elif_else(value):\n"
        "    if value > 0:\n"
        "        return 1\n"
        "    elif value < 0:\n"
        "        return -1\n"
        "    else:\n"
        "        return 0\n",
        3,
    ),
    (
        "for_loop",
        "def for_loop(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item\n"
        "    return total\n",
        2,
    ),
    (
        "while_loop",
        "def while_loop(value):\n    while value > 0:\n        value -= 1\n    return value\n",
        2,
    ),
    (
        "boolean_operators",
        "def boolean_operators(left, right):\n    return left and right or not left\n",
        1,
    ),
    (
        "comprehension",
        "def comprehension(items):\n    return [item for item in items if item]\n",
        1,
    ),
    (
        "nested_branches",
        "def nested_branches(left, right):\n"
        "    if left:\n"
        "        if right:\n"
        "            return 1\n"
        "        return 2\n"
        "    return 3\n",
        3,
    ),
    ("assert_guard", "def assert_guard(value):\n    assert value\n    return value\n", 2),
    (
        "try_except",
        "def try_except():\n    try:\n        return 1\n    except ValueError:\n        return 2\n",
        2,
    ),
    ("ternary", "def ternary(value):\n    return 1 if value else 0\n", 2),
    (
        "for_with_if",
        "def for_with_if(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        if item:\n"
        "            total += item\n"
        "    return total\n",
        3,
    ),
    (
        "five_decisions",
        "def five_decisions(value):\n"
        "    if value > 0:\n"
        "        value += 1\n"
        "    if value > 1:\n"
        "        value += 1\n"
        "    for _ in range(value):\n"
        "        value += 0\n"
        "    while value > 10:\n"
        "        value -= 1\n"
        "    return value\n",
        5,
    ),
    (
        "ten_decisions",
        "def ten_decisions(value):\n"
        "    if value > 0:\n"
        "        value += 1\n"
        "    if value > 1:\n"
        "        value += 1\n"
        "    if value > 2:\n"
        "        value += 1\n"
        "    if value > 3:\n"
        "        value += 1\n"
        "    if value > 4:\n"
        "        value += 1\n"
        "    if value > 5:\n"
        "        value += 1\n"
        "    if value > 6:\n"
        "        value += 1\n"
        "    if value > 7:\n"
        "        value += 1\n"
        "    if value > 8:\n"
        "        value += 1\n"
        "    return value\n",
        10,
    ),
)


@pytest.mark.parametrize(("name", "source", "expected"), _COMPLEXITY_FIXTURES)
def test_complexity_from_source_counts_decision_nodes(
    name: str, source: str, expected: int
) -> None:
    """N3: the integer `C` CRAP squares, asserted for distinct fixtures."""
    assert complexity_from_source(source, name=name, start_line=1) == expected


def test_complexity_from_source_anchors_crap_worked_examples() -> None:
    """Plan 24 band table: C=5, cov=0.5 → 8.125; C=10, cov=0.0 → 110."""
    sources = {name: source for name, source, _ in _COMPLEXITY_FIXTURES}
    five = complexity_from_source(sources["five_decisions"], name="five_decisions", start_line=1)
    ten = complexity_from_source(sources["ten_decisions"], name="ten_decisions", start_line=1)
    assert five == 5
    assert ten == 10
    assert crap_score(five, 0.5) == pytest.approx(8.125)
    assert crap_score(ten, 0.0) == pytest.approx(110.0)


def test_complexity_from_source_matches_function_at_offset_start_line() -> None:
    source = "import os\n\n\ndef offset(value):\n    if value:\n        return 1\n    return 0\n"
    assert complexity_from_source(source, name="offset", start_line=4) == 2


def test_complexity_from_source_returns_none_for_unknown_name() -> None:
    source = "def known(value):\n    return value\n"
    assert complexity_from_source(source, name="missing", start_line=1) is None


def test_complexity_from_source_returns_none_when_start_line_mismatches() -> None:
    source = "def known(value):\n    return value\n"
    assert complexity_from_source(source, name="known", start_line=2) is None


def test_complexity_from_source_returns_none_for_unparseable_source() -> None:
    assert complexity_from_source("def broken(:\n", name="broken", start_line=1) is None
