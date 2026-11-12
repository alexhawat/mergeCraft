"""Biome and oxlint native JSON reporters each get their own parser.

Neither tool emits ESLint's ``[{filePath, messages}]`` array, so wiring them to
``eslint_json`` made biome always unparsable and oxlint silently clean.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.analyzers.support import FIXTURES_DIR

from mergecraft.analyzers.parsers import get_parser
from mergecraft.analyzers.registry import get_manifest

_SOURCE = "const answer = 42;\n\n\ndebugger;\n"


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / "native" / name).read_text(encoding="utf-8")


def _parse(tool_id: str, raw: str, repo_root: Path) -> list:
    manifest = get_manifest(tool_id)
    return get_parser(manifest.parser)(raw, manifest=manifest, repo_root=repo_root)


@pytest.mark.parametrize("tool_id", ["biome", "oxlint"], ids=["biome", "oxlint"])
def test_js_linters_are_not_wired_to_the_eslint_parser(tool_id: str) -> None:
    assert get_manifest(tool_id).parser == f"{tool_id}_json"


def test_biome_report_maps_category_severity_and_line(tmp_path: Path) -> None:
    findings = _parse("biome", _fixture("biome-minimal.json"), tmp_path)

    assert [(f.rule_id, f.severity, f.path, f.start_line) for f in findings] == [
        ("lint/suspicious/noDebugger", "Major", "src/index.js", 4)
    ]


def test_biome_line_falls_back_to_the_file_when_source_is_not_embedded(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text(_SOURCE, encoding="utf-8")
    report = json.loads(_fixture("biome-minimal.json"))
    del report["diagnostics"][0]["location"]["sourceCode"]

    findings = _parse("biome", json.dumps(report), tmp_path)

    assert findings[0].start_line == 4


def test_biome_clean_run_is_empty_and_eslint_shape_is_rejected(tmp_path: Path) -> None:
    assert _parse("biome", '{"summary": {}, "diagnostics": [], "command": "lint"}', tmp_path) == []
    with pytest.raises(ValueError, match="biome"):
        _parse("biome", _fixture("eslint-minimal.json"), tmp_path)


def test_oxlint_array_report_maps_code_severity_and_line(tmp_path: Path) -> None:
    findings = _parse("oxlint", _fixture("oxlint-minimal.json"), tmp_path)

    assert [(f.rule_id, f.severity, f.path, f.start_line) for f in findings] == [
        ("eslint(no-debugger)", "Minor", "src/index.js", 4)
    ]


def test_oxlint_wrapped_report_with_offset_only_spans(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text(_SOURCE, encoding="utf-8")
    diagnostics = json.loads(_fixture("oxlint-minimal.json"))
    diagnostics[0]["labels"][0]["span"] = {"offset": 21, "length": 9}
    wrapped = {"diagnostics": diagnostics, "number_of_files": 1, "number_of_rules": 100}

    findings = _parse("oxlint", json.dumps(wrapped), tmp_path)

    assert [(f.path, f.start_line) for f in findings] == [("src/index.js", 4)]


def test_oxlint_rejects_eslint_shaped_output(tmp_path: Path) -> None:
    """An ESLint-style array has no oxlint fields; it must not read as findings or clean."""
    with pytest.raises(ValueError, match="oxlint"):
        _parse("oxlint", '{"results": []}', tmp_path)
