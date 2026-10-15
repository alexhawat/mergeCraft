"""Issue #983 — Ultramarine catalog, cost math, and generation param mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.agents.curated_model_catalog import (
    ULTRAMARINE_1_FLASH_SLUG,
    apply_catalog_cost_to_usage,
    compute_review_cost_usd,
    curated_model_entry,
)
from mergecraft.agents.openai_generation_params import (
    resolve_openai_generation_params,
    validate_generation_params_for_model,
)
from mergecraft.agents.shared import AgentUsage
from mergecraft.agents.verifier import AgentFinding
from mergecraft.config.settings import RepoSettings
from mergecraft.review.terminal_submission import (
    format_finding_provenance_line,
    merge_reviewer_findings,
)
from mergecraft.utils.agent_resolve import ModelFallbackPolicyError, resolve_harness


def test_curated_ultramarine_entry_is_registered() -> None:
    entry = curated_model_entry(ULTRAMARINE_1_FLASH_SLUG)
    assert entry is not None
    assert entry.input_usd_per_mtok == 0.15
    assert entry.cached_input_usd_per_mtok == 0.03
    assert entry.output_usd_per_mtok == 0.50
    assert entry.default_max_completion_tokens == 8192
    assert entry.default_reasoning_effort == "low"


def test_compute_review_cost_splits_cached_and_uncached_input() -> None:
    # 1_000_000 prompt tokens with 950_000 cached → 50k uncached @ $0.15, 950k @ $0.03
    cost = compute_review_cost_usd(
        model=ULTRAMARINE_1_FLASH_SLUG,
        input_tokens=1_000_000,
        output_tokens=20_000,
        cache_read_tokens=950_000,
    )
    assert cost is not None
    expected = (50_000 * 0.15 + 950_000 * 0.03 + 20_000 * 0.50) / 1_000_000
    assert cost == pytest.approx(expected, rel=1e-9)
    assert cost > 0


def test_apply_catalog_cost_fills_missing_usage_cost() -> None:
    usage = AgentUsage(
        agent="opencode",
        input_tokens=1_000_000,
        output_tokens=20_000,
        cache_read_tokens=950_000,
    )
    enriched = apply_catalog_cost_to_usage(usage, model=ULTRAMARINE_1_FLASH_SLUG)
    assert enriched is not None
    assert enriched.cost_usd is not None
    assert enriched.cost_usd == pytest.approx(
        compute_review_cost_usd(
            model=ULTRAMARINE_1_FLASH_SLUG,
            input_tokens=1_000_000,
            output_tokens=20_000,
            cache_read_tokens=950_000,
        )
        or 0.0,
        rel=1e-9,
    )


def test_max_completion_tokens_resolves_from_catalog_and_overrides() -> None:
    params = resolve_openai_generation_params(
        ULTRAMARINE_1_FLASH_SLUG,
        {"max_completion_tokens": 4096, "reasoning_effort": "low"},
    )
    assert params.max_completion_tokens == 4096
    assert params.max_tokens == 4096


def test_ultramarine_rejects_non_opencode_harness() -> None:
    settings = RepoSettings.model_validate(
        {"harness": "codex", "model": ULTRAMARINE_1_FLASH_SLUG},
    )
    with pytest.raises(ModelFallbackPolicyError, match="harness: opencode"):
        resolve_harness(settings, ULTRAMARINE_1_FLASH_SLUG)

    claude_settings = RepoSettings.model_validate(
        {"harness": "claude", "model": ULTRAMARINE_1_FLASH_SLUG},
    )
    with pytest.raises(ModelFallbackPolicyError, match="harness: opencode"):
        resolve_harness(claude_settings, ULTRAMARINE_1_FLASH_SLUG)


def test_validate_generation_applies_catalog_defaults_for_ultramarine() -> None:
    validate_generation_params_for_model(ULTRAMARINE_1_FLASH_SLUG, {})
    params = resolve_openai_generation_params(ULTRAMARINE_1_FLASH_SLUG, {})
    assert params.max_completion_tokens == 8192
    assert params.reasoning_effort == "low"


def test_opencode_generation_options_include_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.agents.conftest import make_agent_run_context
    from tests.cli.support_provider_registry import bootstrap_opencode_gateway

    slug = ULTRAMARINE_1_FLASH_SLUG
    bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="paperinstruments",
        model_id="ultramarine-1-flash",
        api_key="test-key",
        url="https://api.paperinstruments.com/v1",
    )
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_1",
        json.dumps(
            {
                "max_completion_tokens": 8192,
                "reasoning_effort": "low",
                "context_limit": 128000,
            }
        ),
    )
    from mergecraft.agents.opencode import build_security_config

    ctx = make_agent_run_context(tmp_path, resolved_model=slug)
    config = json.loads(build_security_config(ctx, slug))
    provider = config["provider"]["paperinstruments"]
    model_entry = provider["models"]["ultramarine-1-flash"]
    assert model_entry["limit"]["output"] == 8192
    assert model_entry["options"]["reasoning_effort"] == "low"


def test_multi_reviewer_merge_attributes_and_dedupes() -> None:
    left = [
        {
            "path": "a.py",
            "body": "bug",
            "line": 10,
            "severity": "Minor",
            "raised_by": "reviewer",
            "raised_by_model": "anthropic/claude-sonnet",
        }
    ]
    right = [
        {
            "path": "a.py",
            "body": "bug",
            "line": 10,
            "severity": "Minor",
            "raised_by": "reviewer2",
            "raised_by_model": ULTRAMARINE_1_FLASH_SLUG,
        }
    ]
    merged = merge_reviewer_findings(
        [("reviewer", left), ("reviewer2", right)],
        apply_placement=False,
    )
    assert len(merged) == 1
    raised = merged[0].get("raised_by")
    assert isinstance(raised, list)
    assert set(raised) == {"reviewer", "reviewer2"}
    by_model = merged[0].get("raised_by_models")
    assert isinstance(by_model, dict)
    assert by_model == {
        "reviewer": "anthropic/claude-sonnet",
        "reviewer2": ULTRAMARINE_1_FLASH_SLUG,
    }
    assert "raised_by_model" not in merged[0]
    AgentFinding.model_validate(merged[0])


def test_deduped_finding_omits_model_map_when_reviewer_has_no_model() -> None:
    left = [
        {
            "path": "a.py",
            "body": "bug",
            "line": 10,
            "severity": "Minor",
            "raised_by_model": "anthropic/claude-sonnet",
        }
    ]
    right = [{"path": "a.py", "body": "bug", "line": 10, "severity": "Minor"}]
    merged = merge_reviewer_findings(
        [("reviewer", left), ("reviewer2", right)],
        apply_placement=False,
    )
    assert merged[0]["raised_by_models"] == {"reviewer": "anthropic/claude-sonnet"}
    AgentFinding.model_validate(merged[0])


def test_opencode_emits_catalog_output_cap_without_context_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.agents.conftest import make_agent_run_context
    from tests.cli.support_provider_registry import bootstrap_opencode_gateway

    slug = ULTRAMARINE_1_FLASH_SLUG
    bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="paperinstruments",
        model_id="ultramarine-1-flash",
        api_key="test-key",
        url="https://api.paperinstruments.com/v1",
    )
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_1",
        json.dumps({"reasoning_effort": "low"}),
    )
    from mergecraft.agents.opencode import build_security_config

    ctx = make_agent_run_context(tmp_path, resolved_model=slug)
    config = json.loads(build_security_config(ctx, slug))
    model_entry = config["provider"]["paperinstruments"]["models"]["ultramarine-1-flash"]
    assert "limit" not in model_entry
    assert model_entry["options"]["max_completion_tokens"] == 8192


def test_provenance_line_includes_model_when_set() -> None:
    line = format_finding_provenance_line(
        "reviewer2",
        raised_by_model=ULTRAMARINE_1_FLASH_SLUG,
    )
    assert line is not None
    assert "reviewer2" in line
    assert ULTRAMARINE_1_FLASH_SLUG in line


def test_provenance_line_pairs_reviewers_with_models() -> None:
    line = format_finding_provenance_line(
        ["reviewer", "reviewer2"],
        raised_by_models={
            "reviewer": "anthropic/claude-sonnet",
            "reviewer2": ULTRAMARINE_1_FLASH_SLUG,
        },
    )
    assert line is not None
    assert "`reviewer` (`anthropic/claude-sonnet`)" in line
    assert "`reviewer2` (`paperinstruments/ultramarine-1-flash`)" in line
