"""native_output_to_sarif: converter failure must not look like a clean scan."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "native_output_to_sarif",
    _ROOT / "scripts" / "native_output_to_sarif.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
ConverterError = _MOD.ConverterError
bandit_to_sarif = _MOD.bandit_to_sarif
main = _MOD.main
mypy_to_sarif = _MOD.mypy_to_sarif


def test_valid_empty_bandit_results_is_clean_sarif() -> None:
    doc = bandit_to_sarif('{"results": []}')
    assert doc["runs"][0]["results"] == []


def test_invalid_bandit_json_is_converter_failure() -> None:
    with pytest.raises(ConverterError):
        bandit_to_sarif("{not json")


def test_empty_bandit_input_is_converter_failure() -> None:
    with pytest.raises(ConverterError):
        bandit_to_sarif("  \n")


def test_bandit_object_without_results_array_is_converter_failure() -> None:
    with pytest.raises(ConverterError):
        bandit_to_sarif('{"errors": []}')


def test_garbage_mypy_input_is_converter_failure() -> None:
    with pytest.raises(ConverterError):
        mypy_to_sarif("this is not json\n")


def test_missing_input_file_does_not_write_clean_sarif(tmp_path: Path) -> None:
    dest = tmp_path / "out.sarif"
    missing = tmp_path / "no-such.json"
    assert main(["mypy", str(missing), str(dest)]) == 1
    assert not dest.exists()


def test_invalid_bandit_file_does_not_write_clean_sarif(tmp_path: Path) -> None:
    src = tmp_path / "bandit.json"
    dest = tmp_path / "bandit.sarif"
    src.write_text("not-json", encoding="utf-8")
    assert main(["bandit", str(src), str(dest)]) == 1
    assert not dest.exists()


def test_valid_bandit_finding_writes_sarif(tmp_path: Path) -> None:
    src = tmp_path / "bandit.json"
    dest = tmp_path / "bandit.sarif"
    src.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "test_id": "B201",
                        "issue_severity": "HIGH",
                        "issue_text": "flask debug",
                        "filename": "app.py",
                        "line_number": 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(["bandit", str(src), str(dest)]) == 0
    doc = json.loads(dest.read_text(encoding="utf-8"))
    assert doc["runs"][0]["results"][0]["ruleId"] == "B201"


def test_bandit_line_range_matches_parser_end_line() -> None:
    raw = json.dumps(
        {
            "results": [
                {
                    "test_id": "B101",
                    "issue_severity": "HIGH",
                    "issue_text": "assert used",
                    "filename": "app.py",
                    "line_number": 4,
                    "line_range": [4, 9],
                }
            ]
        }
    )
    doc = bandit_to_sarif(raw)
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 4
    assert region["endLine"] == 9


def test_empty_mypy_input_is_converter_failure() -> None:
    with pytest.raises(ConverterError):
        mypy_to_sarif("  \n")


def test_explicit_empty_mypy_array_is_clean_sarif() -> None:
    doc = mypy_to_sarif("[]")
    assert doc["runs"][0]["results"] == []


def test_invalid_mypy_line_number_is_converter_failure() -> None:
    with pytest.raises(ConverterError, match="line number"):
        mypy_to_sarif(
            '{"file": "a.py", "line": "not-a-line", "message": "x", "code": "attr-defined"}\n'
        )


def test_invalid_line_number_does_not_write_clean_sarif(tmp_path: Path) -> None:
    src = tmp_path / "mypy.json"
    dest = tmp_path / "mypy.sarif"
    src.write_text(
        '{"file": "a.py", "line": "nope", "message": "x", "code": "attr-defined"}\n',
        encoding="utf-8",
    )
    assert main(["mypy", str(src), str(dest)]) == 1
    assert not dest.exists()


def test_truncated_mypy_jsonl_is_converter_failure_not_partial_scan() -> None:
    good = '{"file": "a.py", "line": 1, "message": "x", "code": "attr-defined"}\n'
    truncated = '{"file": "b.py", "line": 2, "message":'
    with pytest.raises(ConverterError, match=r"truncated|invalid"):
        mypy_to_sarif(good + truncated)


def test_bandit_non_object_results_row_is_converter_failure() -> None:
    with pytest.raises(ConverterError, match="non-object"):
        bandit_to_sarif('{"results": ["not-an-object"]}')


def test_sarif_converters_use_require_line_not_as_line() -> None:
    import inspect

    from mergecraft.analyzers.parsers._common import coerce_line, require_line

    source = inspect.getsource(_MOD)
    assert "def _as_line" not in source
    assert "require_line" in source
    assert "parse_line=require_line" in source
    assert "fail_closed" not in source
    assert require_line(None) == 1
    assert coerce_line("nope") == 1
    with pytest.raises(ValueError, match="line number"):
        require_line("nope")
    with pytest.raises(ValueError, match="line number"):
        require_line(True)
    with pytest.raises(ConverterError, match="line number"):
        mypy_to_sarif('{"file": "a.py", "line": "nope", "message": "x", "code": "attr-defined"}\n')
    with pytest.raises(ConverterError, match="line number"):
        mypy_to_sarif('{"file": "a.py", "line": true, "message": "x", "code": "attr-defined"}\n')
    with pytest.raises(ConverterError, match="line number"):
        bandit_to_sarif(
            '{"results": [{"test_id": "B101", "issue_severity": "HIGH",'
            ' "issue_text": "assert", "filename": "a.py", "line_number": "nope"}]}'
        )
