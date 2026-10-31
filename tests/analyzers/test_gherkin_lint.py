"""Optional Gherkin ``.feature`` lint analyzer — syntax and structure only (#854)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.analyzers.finding import Finding
from tests.analyzers.support import FIXTURES_DIR, import_module

_FIXTURE = FIXTURES_DIR / "native" / "gherkin-lint-minimal.json"


def _manifest():
    return import_module("mergecraft.analyzers.registry").get_manifest("gherkin-lint")


def _parse(raw: str) -> list[Finding]:
    parsers = import_module("mergecraft.analyzers.parsers")
    return parsers.get_parser(_manifest().parser)(raw, manifest=_manifest(), repo_root=Path("."))


def test_manifest_is_a_repo_native_static_linter_that_is_not_default_on() -> None:
    manifest = _manifest()
    assert manifest.category == "lint"
    assert manifest.scope == "diff"
    assert manifest.runtime == "repo-native"
    assert manifest.default_enabled is False
    assert "*.feature" in manifest.detect.files
    assert manifest.command[0] == "gherkin-lint"


def test_manifest_never_executes_scenarios_or_step_definitions() -> None:
    command = " ".join(_manifest().command).casefold()
    assert "cucumber" not in command
    assert "--require" not in command


def test_broken_gherkin_yields_a_typed_major_syntax_finding() -> None:
    findings = _parse(_FIXTURE.read_text(encoding="utf-8"))

    syntax = [finding for finding in findings if finding.rule_id == "unexpected-error"]
    assert syntax, "a parse failure must surface as a finding"
    assert syntax[0].severity == "Major"
    assert syntax[0].tool == "gherkin-lint"
    assert syntax[0].path.endswith(".feature")
    assert syntax[0].start_line is not None
    assert syntax[0].source == "analyzer"


def test_structure_lint_rules_are_graded_below_syntax_errors() -> None:
    findings = _parse(_FIXTURE.read_text(encoding="utf-8"))

    structural = [finding for finding in findings if finding.rule_id == "no-dupe-scenario-names"]
    assert structural
    assert structural[0].severity == "Minor"


def test_valid_feature_is_clean() -> None:
    raw = json.dumps([{"filePath": "features/ok.feature", "errors": []}])
    assert _parse(raw) == []
    assert _parse("[]") == []


@pytest.mark.parametrize("raw", ["", "not-json", "{", "error: gherkin-lint exploded"])
def test_garbage_output_raises_rather_than_reading_as_clean(raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse(raw)


def test_skips_with_a_named_reason_when_no_feature_file_changed() -> None:
    adapters = import_module("mergecraft.analyzers.adapters")

    result = adapters.run_adapter(
        tool_id="gherkin-lint",
        repo_root=FIXTURES_DIR / "repo",
        changed_files=["README.md", "src/app.py"],
    )

    assert result.skipped is True
    assert result.findings == []
    assert result.skip_reason
    assert "gherkin-lint" in result.skip_reason


def test_never_selected_when_no_feature_file_changed(tmp_path: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")

    selected = registry.detect_enabled(
        repo_root=tmp_path,
        changed_files=["README.md"],
        settings_overrides={"analyzers": {"overrides": {"gherkin-lint": {"enabled": True}}}},
    )

    assert "gherkin-lint" not in {manifest.id for manifest in selected}


def test_selected_only_when_the_repo_opts_in(tmp_path: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")

    off = registry.detect_enabled(
        repo_root=tmp_path, changed_files=["features/a.feature"], settings_overrides={}
    )
    on = registry.detect_enabled(
        repo_root=tmp_path,
        changed_files=["features/a.feature"],
        settings_overrides={"analyzers": {"overrides": {"gherkin-lint": {"enabled": True}}}},
    )

    assert "gherkin-lint" not in {manifest.id for manifest in off}
    assert "gherkin-lint" in {manifest.id for manifest in on}


def test_untrusted_and_shell_disabled_behaviour_matches_markdownlint() -> None:
    trust = import_module("mergecraft.analyzers.trust")
    registry = import_module("mergecraft.analyzers.registry")
    gherkin = registry.get_manifest("gherkin-lint")
    peer = registry.get_manifest("markdownlint")

    for shell in ("disabled", "restricted"):
        left = trust.evaluate_manifest_for_shell(manifest=gherkin, shell=shell)
        right = trust.evaluate_manifest_for_shell(manifest=peer, shell=shell)
        assert left.skipped == right.skipped
    skipped = trust.evaluate_manifest_for_shell(manifest=gherkin, shell="disabled")
    assert skipped.skipped is True
    assert skipped.reason
    assert "gherkin-lint" in skipped.reason

    tier = trust.evaluate_manifest_for_tier(manifest=gherkin, tier="untrusted", cause="fork")
    peer_tier = trust.evaluate_manifest_for_tier(manifest=peer, tier="untrusted", cause="fork")
    assert tier.skipped == peer_tier.skipped


def test_conservative_default_config_attaches_only_when_the_repo_has_none(tmp_path: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    argv = ("gherkin-lint", "-f", "json", resolve.FILES_TOKEN)

    patched, note = resolve._apply_config_absent_patches("gherkin-lint", tmp_path, argv)
    assert patched != argv
    assert any("gherkin-lint-default-config" in part for part in patched)
    assert note

    (tmp_path / ".gherkin-lintrc").write_text("{}\n", encoding="utf-8")
    unpatched, no_note = resolve._apply_config_absent_patches("gherkin-lint", tmp_path, argv)
    assert unpatched == argv
    assert no_note is None
