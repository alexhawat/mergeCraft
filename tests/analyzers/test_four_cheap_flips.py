"""Batch W (#338) detect fixtures and auto-flip pins for four cheap catalog tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import FIXTURES_DIR, INLINE_BUDGET, import_module

FOUR_CHEAP_FLIPS: tuple[str, ...] = ("golangci-lint", "clippy", "rubocop", "phpstan")
BATCH_W_FIXTURES = FIXTURES_DIR / "batch-w"

# W1.1 language markers. A wrong detect block fails here before the W2 flip.
_LANGUAGE_DETECT_PATHS: tuple[tuple[str, str], ...] = (
    ("golangci-lint", "go.mod"),
    ("golangci-lint", "hello.go"),
    ("golangci-lint", "pkg/hello.go"),
    ("clippy", "Cargo.toml"),
    ("clippy", "src/lib.rs"),
    ("rubocop", "Gemfile"),
    ("rubocop", "hello.rb"),
    ("rubocop", "lib/hello.rb"),
    ("phpstan", "composer.json"),
    ("phpstan", "hello.php"),
    ("phpstan", "src/hello.php"),
)

_RUBOCOP_CONFIG_NAMES: tuple[str, ...] = (
    ".rubocop.yml",
    ".rubocop.yaml",
    ".rubocop.yml.dist",
)

_AUTO_DETECT_CASES: tuple[tuple[str, Path, list[str]], ...] = (
    ("golangci-lint", BATCH_W_FIXTURES / "go", ["hello.go", "go.mod"]),
    ("clippy", BATCH_W_FIXTURES / "rust", ["Cargo.toml", "src/lib.rs"]),
    ("rubocop", BATCH_W_FIXTURES / "ruby", ["hello.rb", "Gemfile"]),
    ("phpstan", BATCH_W_FIXTURES / "php", ["hello.php", "composer.json"]),
)


def _registry():
    return import_module("mergecraft.analyzers.registry")


def _enabled_ids(repo_root: Path, changed_files: list[str]) -> set[str]:
    return {
        manifest.id
        for manifest in _registry().detect_enabled(
            repo_root=repo_root,
            changed_files=changed_files,
            settings_overrides={},
        )
    }


def _argv_has_level_zero(argv: tuple[str, ...]) -> bool:
    if "--level=0" in argv:
        return True
    try:
        index = argv.index("--level")
    except ValueError:
        return False
    return index + 1 < len(argv) and argv[index + 1] == "0"


@pytest.mark.parametrize(("tool_id", "changed"), _LANGUAGE_DETECT_PATHS)
def test_language_marker_matches_detect_globs(tool_id: str, changed: str) -> None:
    registry = _registry()
    manifest = registry.get_manifest(tool_id)
    matched = registry.filter_changed_files_for_manifest(manifest, [changed])
    assert matched == [changed], (
        f"{tool_id} detect.files must match {changed!r}; got {matched!r} "
        f"from {list(manifest.detect.files)!r}"
    )


@pytest.mark.parametrize("tool_id", FOUR_CHEAP_FLIPS)
def test_language_markers_do_not_match_unrelated_paths(tool_id: str) -> None:
    registry = _registry()
    manifest = registry.get_manifest(tool_id)
    assert registry.filter_changed_files_for_manifest(manifest, ["README.md"]) == []
    assert registry.filter_changed_files_for_manifest(manifest, []) == []


def test_rubocop_detect_matches_shipped_config_glob() -> None:
    registry = _registry()
    manifest = registry.get_manifest("rubocop")
    assert registry.filter_changed_files_for_manifest(manifest, [".rubocop.yml"]) == [
        ".rubocop.yml"
    ]


@pytest.mark.parametrize("tool_id", FOUR_CHEAP_FLIPS)
def test_four_cheap_flips_have_catalog_check_sarif_fixture(tool_id: str) -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    manifest = _registry().get_manifest(tool_id)
    assert docs.manifest_has_fixture(manifest, fixture_root=FIXTURES_DIR), (
        f"{tool_id} must keep a catalog-check-shaped parser fixture (D15)"
    )


@pytest.mark.parametrize("tool_id", FOUR_CHEAP_FLIPS)
def test_four_cheap_flips_declare_timeout(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.timeout_s > 0


@pytest.mark.parametrize("tool_id", FOUR_CHEAP_FLIPS)
def test_four_cheap_flips_default_enabled_auto(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.default_enabled == "auto"


@pytest.mark.parametrize(("tool_id", "repo", "changed"), _AUTO_DETECT_CASES)
def test_four_cheap_flips_auto_enables_on_language_markers(
    tool_id: str, repo: Path, changed: list[str]
) -> None:
    assert repo.is_dir(), f"missing Batch W fixture repo: {repo}"
    assert tool_id in _enabled_ids(repo, changed)


def test_empty_changed_files_do_not_enable_four_cheap_flips() -> None:
    ids = _enabled_ids(BATCH_W_FIXTURES / "go", [])
    assert ids.isdisjoint(FOUR_CHEAP_FLIPS)


@pytest.mark.parametrize("config_name", _RUBOCOP_CONFIG_NAMES)
def test_rubocop_auto_fires_when_config_is_present(tmp_path: Path, config_name: str) -> None:
    (tmp_path / config_name).write_text("AllCops:\n  NewCops: enable\n", encoding="utf-8")
    (tmp_path / "hello.rb").write_text("puts 1\n", encoding="utf-8")
    assert "rubocop" in _enabled_ids(tmp_path, ["hello.rb"])


def test_rubocop_auto_fires_when_gemfile_declares_rubocop(tmp_path: Path) -> None:
    (tmp_path / "Gemfile").write_text(
        'source "https://rubygems.org"\n\ngem "rubocop"\n',
        encoding="utf-8",
    )
    (tmp_path / "hello.rb").write_text("puts 1\n", encoding="utf-8")
    assert "rubocop" in _enabled_ids(tmp_path, ["hello.rb"])


def test_rubocop_without_config_is_not_enabled(tmp_path: Path) -> None:
    (tmp_path / "hello.rb").write_text("puts 1\n", encoding="utf-8")
    (tmp_path / "Gemfile").write_text(
        'source "https://rubygems.org"\n',
        encoding="utf-8",
    )
    assert "rubocop" not in _enabled_ids(tmp_path, ["hello.rb", "Gemfile"])


def test_rubocop_without_config_skips_unavailable_not_a_cop_dump(tmp_path: Path) -> None:
    adapters = import_module("mergecraft.analyzers.adapters")
    (tmp_path / "hello.rb").write_text("puts 1\n", encoding="utf-8")
    result = adapters.run_adapter(
        tool_id="rubocop",
        repo_root=tmp_path,
        changed_files=["hello.rb"],
        tier="trusted",
    )
    assert result.skipped, "D11: no RuboCop config must not dump default cops"
    assert result.skip_reason
    assert not result.findings
    reason = result.skip_reason.casefold()
    assert "unavailable" in reason or "skip" in reason or "not found" in reason


def test_phpstan_neon_globs_match_before_flip() -> None:
    registry = _registry()
    manifest = registry.get_manifest("phpstan")
    for changed in ("phpstan.neon", "phpstan.neon.dist"):
        assert registry.filter_changed_files_for_manifest(manifest, [changed]) == [changed]


def test_phpstan_without_neon_runs_at_level_zero(tmp_path: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    (tmp_path / "composer.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "hello.php").write_text("<?php\n", encoding="utf-8")
    manifest = _registry().get_manifest("phpstan")
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=True,
        repo_tool_path="/usr/bin/phpstan",
        managed_available=False,
        container_available=False,
    )
    assert plan.mode != "skip"
    argv = resolve.expand_analyzer_argv(plan.argv, repo_root=tmp_path, changed_files=["hello.php"])
    assert _argv_has_level_zero(argv), f"D12: no neon must pass --level=0; got {argv!r}"


def test_phpstan_with_neon_does_not_force_level_zero() -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    repo = BATCH_W_FIXTURES / "php"
    manifest = _registry().get_manifest("phpstan")
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=repo,
        repo_has_tool=True,
        repo_tool_path="/usr/bin/phpstan",
        managed_available=False,
        container_available=False,
    )
    if plan.mode == "skip":
        pytest.skip(plan.reason or "phpstan unresolved")
    argv = resolve.expand_analyzer_argv(plan.argv, repo_root=repo, changed_files=["hello.php"])
    assert not _argv_has_level_zero(argv), (
        f"D12: phpstan.neon present must use the neon, not --level=0; got {argv!r}"
    )


@pytest.mark.parametrize("tool_id", list(FOUR_CHEAP_FLIPS))
def test_flipped_tool_reports_unavailable_when_toolchain_absent(
    tool_id: str, tmp_path: Path
) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    run = import_module("mergecraft.analyzers.run")
    manifest = _registry().get_manifest(tool_id)
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=False,
        ci_artifact_available=False,
        managed_available=False,
        container_available=False,
        allow_repo_binaries=False,
    )
    assert plan.mode == "skip"
    assert plan.reason
    outcome = run.run_plan(plan)
    assert outcome.status == "unavailable"


@pytest.mark.parametrize("tool_id", FOUR_CHEAP_FLIPS)
def test_flipped_tool_plan_carries_manifest_timeout(tool_id: str, tmp_path: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = _registry().get_manifest(tool_id)
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=True,
        repo_tool_path=f"/usr/bin/{manifest.command[0]}",
        managed_available=True,
        container_available=False,
    )
    if plan.mode == "skip":
        pytest.skip(plan.reason or f"{tool_id} unresolved")
    assert plan.timeout_s == manifest.timeout_s


def test_four_cheap_flips_findings_honor_inline_budget() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    finding_mod = import_module("mergecraft.analyzers.finding")
    findings = [
        finding_mod.make_finding(
            tool=tool_id,
            rule_id="rule",
            category="Maintainability & Code Quality",
            severity="Major",
            confidence="likely",
            message=f"{tool_id} finding {index}",
            path=f"src/{tool_id}-{index}.ext",
            start_line=index,
            end_line=index,
            source="analyzer",
        )
        for tool_id in FOUR_CHEAP_FLIPS
        for index in range(1, 4)
    ]
    placement = budget.place_findings(findings, inline_budget=INLINE_BUDGET)
    assert len(placement.inline) <= INLINE_BUDGET
    assert placement.mechanical_section is not None
