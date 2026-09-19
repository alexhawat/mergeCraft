"""C0 config surface — ciEvidence artifacts, coverage/mutation blocks, FindingSource."""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

import pytest
from pydantic import ValidationError

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
