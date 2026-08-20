"""Native parsers for auto-on tools whose stdout is not SARIF."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.analyzers.support import FIXTURES_DIR, import_module

_CASES: tuple[tuple[str, str, str, str], ...] = (
    ("htmlhint", "htmlhint_json", "native/htmlhint-minimal.json", "id-unique"),
    ("stylelint", "stylelint_json", "native/stylelint-minimal.json", "color-no-invalid-hex"),
    ("yamllint", "yamllint_parsable", "native/yamllint-minimal.txt", "trailing-spaces"),
    ("markdownlint", "markdownlint_json", "native/markdownlint-minimal.json", "MD041"),
    (
        "prisma-lint",
        "prisma_lint_json",
        "native/prisma-lint-minimal.json",
        "model-name-pascal-case",
    ),
    ("luacheck", "luacheck_text", "native/luacheck-minimal.txt", "W211"),
    ("checkmake", "checkmake_text", "native/checkmake-minimal.txt", "fromlatest"),
    (
        "ember-template-lint",
        "ember_template_lint_json",
        "native/ember-template-lint-minimal.json",
        "no-bare-strings",
    ),
)

_JSON_ARRAY_TOOLS: tuple[tuple[str, str], ...] = (
    ("htmlhint", "htmlhint_json"),
    ("stylelint", "stylelint_json"),
    ("markdownlint", "markdownlint_json"),
)
_JSON_OBJECT_TOOLS: tuple[tuple[str, str], ...] = (("prisma-lint", "prisma_lint_json"),)
_JSON_OBJECT_OR_ARRAY: tuple[tuple[str, str], ...] = (
    ("ember-template-lint", "ember_template_lint_json"),
)
_TEXT_TOOLS: tuple[tuple[str, str], ...] = (
    ("yamllint", "yamllint_parsable"),
    ("luacheck", "luacheck_text"),
    ("checkmake", "checkmake_text"),
)
_GARBAGE = (
    "",
    "not-json",
    "{",
    "[",
    "error: no such command: 'htmlhint'",
    "error: invalid argument",
)


def _manifest(tool_id: str):
    return import_module("mergecraft.analyzers.registry").get_manifest(tool_id)


def _parse(parser_id: str, raw: str, *, tool_id: str):
    parsers = import_module("mergecraft.analyzers.parsers")
    return parsers.get_parser(parser_id)(raw, manifest=_manifest(tool_id), repo_root=Path("."))


@pytest.mark.parametrize(("tool_id", "parser_id", "fixture", "rule_id"), _CASES)
def test_remaining_format_parser_happy_path(
    tool_id: str, parser_id: str, fixture: str, rule_id: str
) -> None:
    raw = (FIXTURES_DIR / fixture).read_text(encoding="utf-8")
    findings = _parse(parser_id, raw, tool_id=tool_id)
    assert findings
    assert findings[0].path
    assert any(finding.rule_id == rule_id for finding in findings)
    assert _manifest(tool_id).parser == parser_id


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_ARRAY_TOOLS)
@pytest.mark.parametrize("raw", _GARBAGE)
def test_json_array_parser_raises_on_garbage(tool_id: str, parser_id: str, raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse(parser_id, raw, tool_id=tool_id)


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_ARRAY_TOOLS)
def test_json_array_parser_empty_array_is_clean(tool_id: str, parser_id: str) -> None:
    assert _parse(parser_id, "[]", tool_id=tool_id) == []


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_TOOLS)
@pytest.mark.parametrize("raw", _GARBAGE)
def test_json_object_parser_raises_on_garbage(tool_id: str, parser_id: str, raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse(parser_id, raw, tool_id=tool_id)


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_TOOLS)
def test_json_object_parser_empty_object_is_clean(tool_id: str, parser_id: str) -> None:
    assert _parse(parser_id, "{}", tool_id=tool_id) == []


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_OR_ARRAY)
@pytest.mark.parametrize("raw", _GARBAGE)
def test_ember_parser_raises_on_garbage(tool_id: str, parser_id: str, raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse(parser_id, raw, tool_id=tool_id)


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_OR_ARRAY)
@pytest.mark.parametrize("raw", ["[]", "{}"])
def test_ember_parser_empty_document_is_clean(tool_id: str, parser_id: str, raw: str) -> None:
    assert _parse(parser_id, raw, tool_id=tool_id) == []


@pytest.mark.parametrize(("tool_id", "parser_id"), _TEXT_TOOLS)
@pytest.mark.parametrize("raw", ["not-json", "error: invalid argument", "usage: yamllint [-h]"])
def test_text_parser_raises_on_non_diagnostic_stdout(
    tool_id: str, parser_id: str, raw: str
) -> None:
    with pytest.raises(ValueError, match=r"diagnostic|expected"):
        _parse(parser_id, raw, tool_id=tool_id)


@pytest.mark.parametrize(("tool_id", "parser_id"), _TEXT_TOOLS)
def test_text_parser_empty_stdout_is_clean(tool_id: str, parser_id: str) -> None:
    assert _parse(parser_id, "", tool_id=tool_id) == []


def test_htmlhint_keeps_format_json() -> None:
    manifest = _manifest("htmlhint")
    assert manifest.command[1:3] == ["--format", "json"]
    assert manifest.parser == "htmlhint_json"


def test_stylelint_keeps_formatter_json() -> None:
    manifest = _manifest("stylelint")
    assert "--formatter" in manifest.command
    assert "json" in manifest.command
    assert manifest.parser == "stylelint_json"


def test_yamllint_uses_parsable_format() -> None:
    manifest = _manifest("yamllint")
    assert manifest.command[1:3] == ["-f", "parsable"]
    assert manifest.parser == "yamllint_parsable"
    assert "sarif" not in manifest.command


def test_markdownlint_uses_json_flag() -> None:
    manifest = _manifest("markdownlint")
    assert "--json" in manifest.command
    assert manifest.parser == "markdownlint_json"


def test_prisma_lint_uses_json_output_format() -> None:
    manifest = _manifest("prisma-lint")
    assert "--output-format" in manifest.command
    assert "json" in manifest.command
    assert manifest.parser == "prisma_lint_json"


def test_luacheck_uses_plain_formatter() -> None:
    manifest = _manifest("luacheck")
    assert manifest.command[1:3] == ["--formatter", "plain"]
    assert manifest.parser == "luacheck_text"


def test_checkmake_uses_parseable_template() -> None:
    manifest = _manifest("checkmake")
    assert "--format" in manifest.command
    assert "{{.FileName}}:{{.LineNumber}}:{{.Rule}}:{{.Violation}}" in manifest.command
    assert manifest.parser == "checkmake_text"


def test_detekt_emits_sarif_on_stdout() -> None:
    manifest = _manifest("detekt")
    assert manifest.parser == "sarif"
    assert "sarif:/dev/stdout" in manifest.command
    assert "sarif:detekt.sarif" not in manifest.command


def test_ember_template_lint_uses_json_formatter() -> None:
    manifest = _manifest("ember-template-lint")
    assert manifest.command[1:3] == ["--format", "json"]
    assert manifest.parser == "ember_template_lint_json"


def test_sarif_parser_extracts_json_from_console_prefix() -> None:
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    manifest = _manifest("detekt")
    body = (FIXTURES_DIR / "sarif/detekt-minimal.sarif.json").read_text(encoding="utf-8")
    raw = "detekt 1.23.7\n" + body
    findings = sarif.parse_sarif(raw, manifest=manifest, repo_root=Path("."))
    assert findings


def test_phpstan_and_brakeman_commands_unchanged() -> None:
    phpstan = _manifest("phpstan")
    brakeman = _manifest("brakeman")
    assert "--error-format=sarif" in phpstan.command
    assert phpstan.parser == "sarif"
    assert brakeman.command[1:4] == ["-f", "sarif", "-o"]
    assert "-" in brakeman.command
    assert brakeman.parser == "sarif"
