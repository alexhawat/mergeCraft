"""Batch Y (#309-#327) leftover A-tier pins: RED until the matching W8-W17 wave."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import FIXTURES_DIR, INLINE_BUDGET, import_module

BATCH_Y_FIXTURES = FIXTURES_DIR / "batch-y"
_CATALOG_DIR = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "analyzers" / "catalog"

_TYPE_CHECKERS: tuple[str, ...] = ("mypy", "pyright", "basedpyright")
_JS_LINTERS: tuple[str, ...] = ("biome", "eslint", "oxlint")
_ALREADY_FROM_WX: tuple[str, ...] = (
    "bandit",
    "vulture",
    "tsc",
    "knip",
    "golangci-lint",
    "govulncheck",
    "clippy",
    "cargo-audit",
    "cargo-deny",
    "phpstan",
    "rubocop",
)
_DO_NOT_READD: tuple[str, ...] = (
    "tsc",
    "bandit",
    "jscpd",
    "govulncheck",
    "knip",
    "vulture",
    "cargo-audit",
    "cargo-deny",
    "typos",
)
_NO_A11Y_IDS: tuple[str, ...] = ("axe", "axe-core", "pa11y", "html-validate", "vnu")
_DEFERRED_SECOND_TIER: tuple[str, ...] = ("shfmt", "dockle", "lychee", "flawfinder", "spotbugs")


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


def _typecheck_ids(ids: set[str]) -> set[str]:
    return ids & set(_TYPE_CHECKERS)


def _js_lint_ids(ids: set[str]) -> set[str]:
    return ids & set(_JS_LINTERS)


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


# --- already green: W/X tools must not be re-added or re-flipped (D7/D10) ---


@pytest.mark.parametrize("tool_id", _ALREADY_FROM_WX)
def test_wx_consumed_tools_stay_auto(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.default_enabled == "auto"


@pytest.mark.parametrize("tool_id", _DO_NOT_READD)
def test_batch_x_ids_are_not_readded_as_a_second_manifest(tool_id: str) -> None:
    path = _CATALOG_DIR / f"{tool_id}.yaml"
    assert path.is_file()
    assert _registry().get_manifest(tool_id).id == tool_id


def test_golangci_lint_clippy_rubocop_phpstan_are_not_reflipped_false() -> None:
    for tool_id in ("golangci-lint", "clippy", "rubocop", "phpstan"):
        assert _registry().get_manifest(tool_id).default_enabled == "auto"


# --- W8 #309 Python leftovers (D16) ---


@pytest.mark.parametrize("tool_id", _TYPE_CHECKERS)
def test_python_type_checkers_share_exclusive_group(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.exclusive_group == "python-typecheck"


def test_python_type_checkers_never_all_three_on_plain_py() -> None:
    repo = BATCH_Y_FIXTURES / "python-noconfig"
    winners = _typecheck_ids(_enabled_ids(repo, ["hello.py"]))
    assert len(winners) <= 1


def test_no_typechecker_config_defaults_to_mypy() -> None:
    repo = BATCH_Y_FIXTURES / "python-noconfig"
    winners = _typecheck_ids(_enabled_ids(repo, ["hello.py"]))
    assert winners == {"mypy"}


def test_mypy_ini_selects_mypy_not_pyright() -> None:
    repo = BATCH_Y_FIXTURES / "python-mypy"
    winners = _typecheck_ids(_enabled_ids(repo, ["hello.py"]))
    assert winners == {"mypy"}


def test_pyrightconfig_selects_pyright_family_not_mypy() -> None:
    repo = BATCH_Y_FIXTURES / "python-pyright"
    winners = _typecheck_ids(_enabled_ids(repo, ["hello.py"]))
    assert len(winners) == 1
    assert winners <= {"pyright", "basedpyright"}
    assert "mypy" not in winners


def test_basedpyright_config_selects_basedpyright() -> None:
    repo = BATCH_Y_FIXTURES / "python-basedpyright"
    winners = _typecheck_ids(_enabled_ids(repo, ["hello.py"]))
    assert winners == {"basedpyright"}


@pytest.mark.parametrize("tool_id", ["flake8", "pylint"])
def test_flake8_pylint_remain_legacy_opt_in(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.default_enabled is False
    assert manifest.exclusive_group == "python-lint"


def test_osv_scanner_covers_requirements_txt() -> None:
    registry = _registry()
    manifest = registry.get_manifest("osv-scanner")
    matched = registry.filter_changed_files_for_manifest(manifest, ["requirements.txt"])
    assert matched == ["requirements.txt"]


def test_osv_scanner_covers_uv_lock() -> None:
    registry = _registry()
    manifest = registry.get_manifest("osv-scanner")
    matched = registry.filter_changed_files_for_manifest(manifest, ["uv.lock"])
    assert matched == ["uv.lock"]


def test_osv_scanner_auto_enables_on_uv_lock_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "python-uv"
    assert "osv-scanner" in _enabled_ids(repo, ["uv.lock", "hello.py"])


def test_pip_audit_is_not_required_when_osv_covers_python_locks() -> None:
    ids = _registry().known_analyzer_ids()
    assert "osv-scanner" in ids


# --- W9 #310 JS/TS leftovers (D17) ---


@pytest.mark.parametrize("tool_id", _JS_LINTERS)
def test_js_linters_share_exclusive_group(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.exclusive_group == "js-lint"


def test_biome_config_wins_js_lint_group() -> None:
    repo = BATCH_Y_FIXTURES / "js-biome"
    assert _js_lint_ids(_enabled_ids(repo, ["src/index.ts"])) == {"biome"}


def test_eslint_config_wins_when_no_biome() -> None:
    repo = BATCH_Y_FIXTURES / "js-eslint"
    assert _js_lint_ids(_enabled_ids(repo, ["src/index.js"])) == {"eslint"}


def test_oxlint_config_wins_when_no_biome_or_eslint() -> None:
    repo = BATCH_Y_FIXTURES / "js-oxlint"
    assert _js_lint_ids(_enabled_ids(repo, ["src/index.js"])) == {"oxlint"}


@pytest.mark.xfail(
    reason="green after W9: biome.json beats eslint config+scripts (D17)",
    strict=False,
)
def test_biome_json_beats_eslint_even_with_eslint_script_signals() -> None:
    repo = BATCH_Y_FIXTURES / "js-biome-over-eslint"
    winners = _js_lint_ids(_enabled_ids(repo, ["src/index.js"]))
    assert winners == {"biome"}


@pytest.mark.xfail(
    reason="green after W9: biome and eslint supports_fix true (#310)",
    strict=False,
)
@pytest.mark.parametrize("tool_id", ["biome", "eslint"])
def test_biome_and_eslint_declare_supports_fix(tool_id: str) -> None:
    manifest = _registry().get_manifest(tool_id)
    assert manifest.supports_fix is True


def test_oxlint_need_not_declare_supports_fix() -> None:
    manifest = _registry().get_manifest("oxlint")
    assert manifest.exclusive_group == "js-lint"


def test_tsc_and_knip_already_present_for_js_ts() -> None:
    registry = _registry()
    assert registry.get_manifest("tsc").default_enabled == "auto"
    assert registry.get_manifest("knip").default_enabled == "auto"


# --- W10 #311/#313/#314 leftovers ---


def test_go_detect_still_matches_go_mod_and_go_files() -> None:
    registry = _registry()
    for tool_id in ("golangci-lint", "govulncheck"):
        manifest = registry.get_manifest(tool_id)
        assert registry.filter_changed_files_for_manifest(manifest, ["go.mod"]) == ["go.mod"]
        assert registry.filter_changed_files_for_manifest(manifest, ["hello.go"]) == ["hello.go"]


@pytest.mark.xfail(
    reason="green after W10: brakeman default_enabled auto (#313)",
    strict=False,
)
def test_brakeman_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("brakeman")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W10: brakeman auto on Rails markers (#313)",
    strict=False,
)
def test_brakeman_auto_enables_on_rails_markers() -> None:
    repo = BATCH_Y_FIXTURES / "rails"
    assert "brakeman" in _enabled_ids(repo, ["hello.rb", "Gemfile", "config/application.rb"])


def test_brakeman_does_not_auto_enable_on_plain_ruby() -> None:
    repo = BATCH_Y_FIXTURES / "ruby-plain"
    assert "brakeman" not in _enabled_ids(repo, ["hello.rb", "Gemfile"])


@pytest.mark.xfail(
    reason="green after W10: bundler-audit catalog YAML (#313)",
    strict=False,
)
def test_bundler_audit_catalog_yaml_exists() -> None:
    path = _CATALOG_DIR / "bundler-audit.yaml"
    assert path.is_file()


@pytest.mark.xfail(
    reason="green after W10: bundler-audit importable auto (#313)",
    strict=False,
)
def test_bundler_audit_is_importable_and_auto() -> None:
    manifest = _registry().get_manifest("bundler-audit")
    assert manifest.id == "bundler-audit"
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W10: bundler-audit detects Gemfile.lock (#313)",
    strict=False,
)
def test_bundler_audit_detects_gemfile_lock() -> None:
    registry = _registry()
    manifest = registry.get_manifest("bundler-audit")
    matched = registry.filter_changed_files_for_manifest(manifest, ["Gemfile.lock"])
    assert matched == ["Gemfile.lock"]


@pytest.mark.xfail(
    reason="green after W10: bundler-audit auto on Gemfile.lock (#313)",
    strict=False,
)
def test_bundler_audit_auto_enables_on_lockfile() -> None:
    repo = BATCH_Y_FIXTURES / "bundler-audit"
    assert "bundler-audit" in _enabled_ids(repo, ["Gemfile.lock", "Gemfile"])


@pytest.mark.xfail(
    reason="green after W10: bundler-audit catalog-check fixture (#313)",
    strict=False,
)
def test_bundler_audit_has_catalog_check_parser_fixture() -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    manifest = _registry().get_manifest("bundler-audit")
    assert docs.manifest_has_fixture(manifest, fixture_root=FIXTURES_DIR)


def test_osv_scanner_already_covers_gemfile_lock() -> None:
    registry = _registry()
    manifest = registry.get_manifest("osv-scanner")
    matched = registry.filter_changed_files_for_manifest(manifest, ["Gemfile.lock"])
    assert matched == ["Gemfile.lock"]


def test_rust_leftovers_already_on_after_wx() -> None:
    registry = _registry()
    for tool_id in ("clippy", "cargo-audit", "cargo-deny"):
        assert registry.get_manifest(tool_id).default_enabled == "auto"


# --- W11 #316 PHP leftovers ---


def test_phpstan_is_enough_default_php_signal() -> None:
    repo = BATCH_Y_FIXTURES / "php-plain"
    ids = _enabled_ids(repo, ["hello.php", "composer.json"])
    assert "phpstan" in ids


def test_phpcs_remains_false_even_with_phpcs_xml() -> None:
    manifest = _registry().get_manifest("phpcs")
    assert manifest.default_enabled is False
    repo = BATCH_Y_FIXTURES / "php-phpcs"
    assert "phpcs" not in _enabled_ids(repo, ["hello.php", "phpcs.xml"])


def test_phpmd_remains_false() -> None:
    manifest = _registry().get_manifest("phpmd")
    assert manifest.default_enabled is False
    repo = BATCH_Y_FIXTURES / "php-plain"
    assert "phpmd" not in _enabled_ids(repo, ["hello.php", "composer.json"])


# --- W12 #315 C/C++ (cppcheck is the default SAST path; not Semgrep languages) ---


@pytest.mark.xfail(
    reason="green after W12: cppcheck default_enabled auto (#315)",
    strict=False,
)
def test_cppcheck_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("cppcheck")
    assert manifest.default_enabled == "auto"


def test_cppcheck_detects_c_and_cpp() -> None:
    registry = _registry()
    manifest = registry.get_manifest("cppcheck")
    assert registry.filter_changed_files_for_manifest(manifest, ["hello.c"]) == ["hello.c"]
    assert registry.filter_changed_files_for_manifest(manifest, ["hello.cpp"]) == ["hello.cpp"]


@pytest.mark.xfail(
    reason="green after W12: cppcheck auto on C/C++ fixtures (#315)",
    strict=False,
)
def test_cppcheck_auto_enables_on_cpp_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "cpp"
    assert "cppcheck" in _enabled_ids(repo, ["hello.cpp", "hello.c"])


def test_clang_tidy_stays_opt_in() -> None:
    manifest = _registry().get_manifest("clang-tidy")
    assert manifest.default_enabled is False
    repo = BATCH_Y_FIXTURES / "cpp"
    assert "clang-tidy" not in _enabled_ids(repo, ["hello.cpp"])


def test_w12_does_not_require_semgrep_c_languages() -> None:
    manifest = _registry().get_manifest("semgrep")
    languages = {lang.casefold() for lang in manifest.languages}
    assert "c" not in languages
    assert "cpp" not in languages
    assert "c++" not in languages


# --- W13 #317/#318 Kotlin + Swift ---


@pytest.mark.xfail(
    reason="green after W13: detekt default_enabled auto (#317)",
    strict=False,
)
def test_detekt_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("detekt")
    assert manifest.default_enabled == "auto"


def test_detekt_detects_kotlin() -> None:
    registry = _registry()
    manifest = registry.get_manifest("detekt")
    assert registry.filter_changed_files_for_manifest(manifest, ["hello.kt"]) == ["hello.kt"]


@pytest.mark.xfail(
    reason="green after W13: detekt auto on *.kt (#317)",
    strict=False,
)
def test_detekt_auto_enables_on_kotlin_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "kotlin"
    assert "detekt" in _enabled_ids(repo, ["hello.kt"])


@pytest.mark.xfail(
    reason="green after W13: swiftlint default_enabled auto (#318)",
    strict=False,
)
def test_swiftlint_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("swiftlint")
    assert manifest.default_enabled == "auto"


def test_swiftlint_detects_swift() -> None:
    registry = _registry()
    manifest = registry.get_manifest("swiftlint")
    assert registry.filter_changed_files_for_manifest(manifest, ["hello.swift"]) == ["hello.swift"]


@pytest.mark.xfail(
    reason="green after W13: swiftlint auto on *.swift (#318)",
    strict=False,
)
def test_swiftlint_auto_enables_on_swift_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "swift"
    assert "swiftlint" in _enabled_ids(repo, ["hello.swift"])


# --- W14 #312 Java (D13 infer stays false) ---


@pytest.mark.xfail(
    reason="green after W14: pmd default_enabled auto (#312)",
    strict=False,
)
def test_pmd_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("pmd")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W14: pmd auto on *.java (#312)",
    strict=False,
)
def test_pmd_auto_enables_on_java_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "java"
    assert "pmd" in _enabled_ids(repo, ["Hello.java", "pom.xml"])


def test_infer_stays_false() -> None:
    manifest = _registry().get_manifest("infer")
    assert manifest.default_enabled is False
    repo = BATCH_Y_FIXTURES / "java"
    assert "infer" not in _enabled_ids(repo, ["Hello.java", "pom.xml"])


def test_java_already_has_default_sast_via_semgrep() -> None:
    manifest = _registry().get_manifest("semgrep")
    assert manifest.default_enabled is True
    languages = {lang.casefold() for lang in manifest.languages}
    assert "java" in languages


# --- W15 #319-#321 SQL / CSS / HTML ---


@pytest.mark.xfail(
    reason="green after W15: sqlfluff default_enabled auto (#319)",
    strict=False,
)
def test_sqlfluff_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("sqlfluff")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W15: sqlfluff auto on *.sql (#319)",
    strict=False,
)
def test_sqlfluff_auto_enables_on_sql_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "sql"
    assert "sqlfluff" in _enabled_ids(repo, ["hello.sql"])


@pytest.mark.xfail(
    reason="green after W15: stylelint default_enabled auto (#320)",
    strict=False,
)
def test_stylelint_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("stylelint")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W15: stylelint auto on *.css (#320)",
    strict=False,
)
def test_stylelint_auto_enables_on_css_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "css"
    assert "stylelint" in _enabled_ids(repo, ["hello.css"])


@pytest.mark.xfail(
    reason="green after W15: htmlhint default_enabled auto (#321)",
    strict=False,
)
def test_htmlhint_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("htmlhint")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W15: htmlhint auto on *.html (#321)",
    strict=False,
)
def test_htmlhint_auto_enables_on_html_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "html"
    assert "htmlhint" in _enabled_ids(repo, ["hello.html"])


@pytest.mark.parametrize("tool_id", _NO_A11Y_IDS)
def test_html_a11y_catalog_gap_no_axe_or_pa11y(tool_id: str) -> None:
    ids = _registry().known_analyzer_ids()
    assert tool_id not in ids
    assert not (_CATALOG_DIR / f"{tool_id}.yaml").is_file()


# --- W16 #322-#324 shell / YAML / Docker ---


def test_shellcheck_already_auto() -> None:
    manifest = _registry().get_manifest("shellcheck")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W16: yamllint default_enabled auto (#323)",
    strict=False,
)
def test_yamllint_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("yamllint")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W16: yamllint auto on *.yaml (#323)",
    strict=False,
)
def test_yamllint_auto_enables_on_yaml_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "yaml"
    assert "yamllint" in _enabled_ids(repo, ["hello.yaml"])


def test_hadolint_already_auto() -> None:
    manifest = _registry().get_manifest("hadolint")
    assert manifest.default_enabled == "auto"


@pytest.mark.parametrize("tool_id", _DEFERRED_SECOND_TIER)
def test_second_tier_and_non_catalog_depth_are_not_added(tool_id: str) -> None:
    ids = _registry().known_analyzer_ids()
    assert tool_id not in ids
    assert not (_CATALOG_DIR / f"{tool_id}.yaml").is_file()


# --- W17 #325-#327 Make / Markdown / Terraform ---


@pytest.mark.xfail(
    reason="green after W17: checkmake default_enabled auto (#325)",
    strict=False,
)
def test_checkmake_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("checkmake")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W17: checkmake auto on Makefile (#325)",
    strict=False,
)
def test_checkmake_auto_enables_on_makefile() -> None:
    repo = BATCH_Y_FIXTURES / "make"
    assert "checkmake" in _enabled_ids(repo, ["Makefile"])


@pytest.mark.xfail(
    reason="green after W17: markdownlint default_enabled auto (#326)",
    strict=False,
)
def test_markdownlint_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("markdownlint")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W17: markdownlint auto on *.md (#326)",
    strict=False,
)
def test_markdownlint_auto_enables_on_markdown_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "markdown"
    assert "markdownlint" in _enabled_ids(repo, ["README.md"])


def test_tflint_and_checkov_already_detect_tf() -> None:
    registry = _registry()
    tflint = registry.get_manifest("tflint")
    checkov = registry.get_manifest("checkov")
    assert registry.filter_changed_files_for_manifest(tflint, ["main.tf"]) == ["main.tf"]
    assert registry.filter_changed_files_for_manifest(checkov, ["main.tf"]) == ["main.tf"]


@pytest.mark.xfail(
    reason="green after W17: tflint default_enabled auto (#327)",
    strict=False,
)
def test_tflint_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("tflint")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W17: checkov default_enabled auto (#327)",
    strict=False,
)
def test_checkov_default_enabled_auto() -> None:
    manifest = _registry().get_manifest("checkov")
    assert manifest.default_enabled == "auto"


@pytest.mark.xfail(
    reason="green after W17: tflint auto on *.tf (#327)",
    strict=False,
)
def test_tflint_auto_enables_on_terraform_fixture() -> None:
    """Both IaC tools must auto-enable; split `iac-scanner` if it collapses them."""
    repo = BATCH_Y_FIXTURES / "terraform"
    assert "tflint" in _enabled_ids(repo, ["main.tf"])


@pytest.mark.xfail(
    reason="green after W17: checkov auto on *.tf (#327)",
    strict=False,
)
def test_checkov_auto_enables_on_terraform_fixture() -> None:
    repo = BATCH_Y_FIXTURES / "terraform"
    assert "checkov" in _enabled_ids(repo, ["main.tf"])


def test_languagetool_stays_opt_in() -> None:
    manifest = _registry().get_manifest("languagetool")
    assert manifest.default_enabled is False


# --- D19: leftover auto-flips still honor budget when they exist ---


def test_batch_y_findings_honor_inline_budget() -> None:
    budget = import_module("mergecraft.analyzers.budget")
    tools = ("cppcheck", "detekt", "swiftlint", "pmd", "sqlfluff", "yamllint")
    findings = [
        _finding(tool=tool_id, path=f"src/{tool_id}-{index}.ext", line=index)
        for tool_id in tools
        for index in range(1, 4)
    ]
    placement = budget.place_findings(findings, inline_budget=INLINE_BUDGET)
    assert len(placement.inline) <= INLINE_BUDGET
    assert placement.mechanical_section is not None
