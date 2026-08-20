"""Batch Z (#328-#336) B-tier detect fixtures and auto-flip pins.

Detect globs, ``default_enabled: auto``, ``detect_enabled`` membership,
``supports_fix``, extra Fortran / PowerShell globs, theme/ember gates, Smarty
``*.tpl`` docs, and the Prisma fallback are real passes after W19. Bare liquid
and bare hbs stay off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import FIXTURES_DIR, INLINE_BUDGET, import_module

B_TIER_IDS: tuple[str, ...] = (
    "luacheck",
    "fortitude",
    "regal",
    "psscriptanalyzer",
    "blinter",
    "shopify-theme-check",
    "smarty-lint",
    "ember-template-lint",
    "prisma-lint",
)
BATCH_Z_FIXTURES = FIXTURES_DIR / "batch-z"
_CATALOG_DIR = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "analyzers" / "catalog"

# W18.1 language markers that already match current catalog YAML.
_LANGUAGE_DETECT_PATHS: tuple[tuple[str, str], ...] = (
    ("luacheck", "hello.lua"),
    ("luacheck", ".luacheckrc"),
    ("luacheck", "src/hello.lua"),
    ("fortitude", "hello.f90"),
    ("fortitude", "hello.f95"),
    ("fortitude", ".fortitude.toml"),
    ("regal", "hello.rego"),
    ("regal", "policy/allow.rego"),
    ("psscriptanalyzer", "hello.ps1"),
    ("psscriptanalyzer", "hello.psm1"),
    ("blinter", "hello.bat"),
    ("blinter", "hello.cmd"),
    ("shopify-theme-check", "hello.liquid"),
    ("shopify-theme-check", ".theme-check.yml"),
    ("shopify-theme-check", "sections/header.liquid"),
    ("smarty-lint", "hello.tpl"),
    ("smarty-lint", ".smarty-lint.json"),
    ("ember-template-lint", "hello.hbs"),
    ("ember-template-lint", ".template-lintrc.js"),
    ("ember-template-lint", "app/templates/application.hbs"),
    ("prisma-lint", "schema.prisma"),
    ("prisma-lint", "prisma/schema.prisma"),
)

# #329 / #331 globs the current YAML does not list — W19 expands detect.files.
_W19_EXTRA_DETECT_PATHS: tuple[tuple[str, str], ...] = (
    ("fortitude", "hello.F90"),
    ("fortitude", "hello.f03"),
    ("fortitude", "hello.f"),
    ("fortitude", "hello.for"),
    ("psscriptanalyzer", "hello.psd1"),
)

_AUTO_DETECT_CASES: tuple[tuple[str, Path, list[str]], ...] = (
    ("luacheck", BATCH_Z_FIXTURES / "lua", ["hello.lua"]),
    ("fortitude", BATCH_Z_FIXTURES / "fortran", ["hello.f90"]),
    ("regal", BATCH_Z_FIXTURES / "rego", ["hello.rego"]),
    ("psscriptanalyzer", BATCH_Z_FIXTURES / "powershell", ["hello.ps1"]),
    ("blinter", BATCH_Z_FIXTURES / "batch", ["hello.bat"]),
    (
        "shopify-theme-check",
        BATCH_Z_FIXTURES / "liquid-theme",
        ["templates/index.liquid", ".theme-check.yml"],
    ),
    ("smarty-lint", BATCH_Z_FIXTURES / "smarty", ["hello.tpl"]),
    (
        "ember-template-lint",
        BATCH_Z_FIXTURES / "ember",
        ["app/templates/application.hbs", "ember-cli-build.js"],
    ),
    ("prisma-lint", BATCH_Z_FIXTURES / "prisma", ["schema.prisma"]),
)

_F_TIER_IDS: tuple[str, ...] = (
    "roslyn",
    "roslyn-analyzers",
    "csharp",
    "c-sharp",
    "dotnet-format",
    "dotnet_format",
    "scalafix",
    "scala",
    "credo",
    "elixir",
    "dart-analyze",
    "dart_analyze",
    "haskell",
    "perl",
    "r",
    "zig",
    "clojure",
    "graphql",
    "nix",
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


def _analyzers_doc_row(tool_id: str) -> str:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    needle = f"| `{tool_id}` |"
    for line in docs.generate_analyzers_doc().splitlines():
        if line.startswith(needle):
            return line
    raise AssertionError(f"missing generated ANALYZERS.md row for {tool_id}")


def _finding(*, tool: str, path: str, line: int):
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool=tool,
        rule_id="rule",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message=f"{tool} finding",
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
    )


# --- already green: detect globs, catalog-check fixtures, D9, D19 ---


@pytest.mark.parametrize(("tool_id", "changed"), _LANGUAGE_DETECT_PATHS)
def test_b_tier_language_marker_matches_detect_globs(tool_id: str, changed: str) -> None:
    registry = _registry()
    manifest = registry.get_manifest(tool_id)
    matched = registry.filter_changed_files_for_manifest(manifest, [changed])
    assert matched == [changed], (
        f"{tool_id} detect.files must match {changed!r}; got {matched!r} "
        f"from {list(manifest.detect.files)!r}"
    )


@pytest.mark.parametrize("tool_id", B_TIER_IDS)
def test_b_tier_markers_do_not_match_unrelated_paths(tool_id: str) -> None:
    registry = _registry()
    manifest = registry.get_manifest(tool_id)
    assert registry.filter_changed_files_for_manifest(manifest, ["README.md"]) == []
    assert registry.filter_changed_files_for_manifest(manifest, []) == []


def test_empty_changed_files_do_not_enable_b_tier() -> None:
    ids = _enabled_ids(BATCH_Z_FIXTURES / "lua", [])
    assert ids.isdisjoint(B_TIER_IDS)


@pytest.mark.parametrize("tool_id", B_TIER_IDS)
def test_b_tier_has_catalog_check_parser_fixture(tool_id: str) -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    manifest = _registry().get_manifest(tool_id)
    assert docs.manifest_has_fixture(manifest, fixture_root=FIXTURES_DIR), (
        f"{tool_id} must keep a catalog-check-shaped parser fixture (D15)"
    )


@pytest.mark.parametrize("tool_id", B_TIER_IDS)
def test_b_tier_declares_timeout(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.timeout_s > 0


@pytest.mark.parametrize("tool_id", list(B_TIER_IDS))
def test_b_tier_reports_unavailable_when_toolchain_absent(tool_id: str, tmp_path: Path) -> None:
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


def test_b_tier_findings_honor_inline_budget() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    findings = [
        _finding(tool=tool_id, path=f"src/{tool_id}-{index}.ext", line=index)
        for tool_id in B_TIER_IDS
        for index in range(1, 4)
    ]
    placement = budget.place_findings(findings, inline_budget=INLINE_BUDGET)
    assert len(placement.inline) <= INLINE_BUDGET
    assert placement.mechanical_section is not None


@pytest.mark.parametrize("tool_id", _F_TIER_IDS)
def test_f_tier_languages_are_not_lifted(tool_id: str) -> None:
    ids = _registry().known_analyzer_ids()
    assert tool_id not in ids
    assert not (_CATALOG_DIR / f"{tool_id}.yaml").is_file()


def test_batch_z_detect_fixture_trees_exist() -> None:
    for relative in (
        "lua/hello.lua",
        "fortran/hello.f90",
        "rego/hello.rego",
        "powershell/hello.ps1",
        "batch/hello.bat",
        "liquid-theme/.theme-check.yml",
        "liquid-theme/sections/header.liquid",
        "liquid-theme/templates/index.liquid",
        "liquid-theme/snippets/icon.liquid",
        "liquid-theme-layout/sections/header.liquid",
        "liquid-theme-layout/templates/index.liquid",
        "liquid-theme-layout/snippets/icon.liquid",
        "liquid-bare/hello.liquid",
        "smarty/hello.tpl",
        "ember/ember-cli-build.js",
        "ember/app/templates/application.hbs",
        "ember-source/package.json",
        "ember-source/app/templates/application.hbs",
        "hbs-bare/hello.hbs",
        "prisma/schema.prisma",
    ):
        path = BATCH_Z_FIXTURES / relative
        assert path.is_file(), f"missing Batch Z detect fixture: {path}"


# --- already green: theme/ember negative gates (stay off on bare files) ---


def test_shopify_theme_check_does_not_auto_enable_on_bare_liquid() -> None:
    repo = BATCH_Z_FIXTURES / "liquid-bare"
    assert "shopify-theme-check" not in _enabled_ids(repo, ["hello.liquid"])


def test_ember_template_lint_does_not_auto_enable_on_bare_hbs() -> None:
    repo = BATCH_Z_FIXTURES / "hbs-bare"
    assert "ember-template-lint" not in _enabled_ids(repo, ["hello.hbs"])


# --- W19 greened: auto flip + extras from the issue table ---


@pytest.mark.parametrize("tool_id", B_TIER_IDS)
def test_b_tier_default_enabled_auto(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.default_enabled == "auto"


@pytest.mark.parametrize(("tool_id", "repo", "changed"), _AUTO_DETECT_CASES)
def test_b_tier_auto_enables_on_detect_markers(
    tool_id: str, repo: Path, changed: list[str]
) -> None:
    assert repo.is_dir(), f"missing Batch Z fixture repo: {repo}"
    assert tool_id in _enabled_ids(repo, changed)


@pytest.mark.parametrize(("tool_id", "changed"), _W19_EXTRA_DETECT_PATHS)
def test_b_tier_w19_extra_detect_globs(tool_id: str, changed: str) -> None:
    registry = _registry()
    manifest = registry.get_manifest(tool_id)
    matched = registry.filter_changed_files_for_manifest(manifest, [changed])
    assert matched == [changed], (
        f"{tool_id} detect.files must match {changed!r}; got {matched!r} "
        f"from {list(manifest.detect.files)!r}"
    )


def test_psscriptanalyzer_declares_supports_fix() -> None:
    manifest = _registry().get_manifest("psscriptanalyzer")
    assert manifest.supports_fix is True


def test_ember_template_lint_declares_supports_fix() -> None:
    manifest = _registry().get_manifest("ember-template-lint")
    assert manifest.supports_fix is True


def test_shopify_theme_check_auto_enables_on_theme_layout_without_yml() -> None:
    repo = BATCH_Z_FIXTURES / "liquid-theme-layout"
    assert "shopify-theme-check" in _enabled_ids(repo, ["templates/index.liquid"])


def test_ember_template_lint_auto_enables_on_ember_source_package_json() -> None:
    repo = BATCH_Z_FIXTURES / "ember-source"
    assert "ember-template-lint" in _enabled_ids(
        repo, ["app/templates/application.hbs", "package.json"]
    )


def test_smarty_lint_docs_note_tpl_ambiguity() -> None:
    row = _analyzers_doc_row("smarty-lint").casefold()
    assert "*.tpl" in row or "tpl" in row
    assert "ambigu" in row


def test_prisma_lint_ships_conservative_fallback_ruleset() -> None:
    hits = [
        path
        for path in _CATALOG_DIR.iterdir()
        if path.is_file()
        and "prisma" in path.stem.casefold()
        and path.name != "prisma-lint.yaml"
        and path.suffix.casefold() in {".yml", ".yaml", ".json"}
    ]
    assert hits, (
        "W19 must ship a conservative prisma-lint fallback ruleset under "
        "src/mergecraft/analyzers/catalog/ (as semgrep-default-rules.yml)"
    )


def test_prisma_lint_without_rules_uses_conservative_fallback(tmp_path: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    (tmp_path / "schema.prisma").write_text("model User { id Int }\n", encoding="utf-8")
    manifest = _registry().get_manifest("prisma-lint")
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=True,
        repo_tool_path="/usr/bin/prisma-lint",
        managed_available=False,
        container_available=False,
    )
    assert plan.mode != "skip"
    argv = resolve.expand_analyzer_argv(
        plan.argv, repo_root=tmp_path, changed_files=["schema.prisma"]
    )
    blob = " ".join(argv).casefold() + " " + (plan.config_note or "").casefold()
    assert any(
        token in blob for token in ("fallback", "default", "@catalog:", "prisma-lint-default")
    ), (
        f"#336: no-rules prisma-lint must use a conservative fallback; got {argv!r} {plan.config_note!r}"
    )
