"""The fix brief CLI transports structured review data read-only."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import jsonschema
import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
_HEAD = "a" * 40
_CHANGE = "acme/app#42"
_MESSAGE = "Opaque text: $(false)\n::warning::example"


@pytest.fixture
def brief_path(tmp_path: Path) -> Path:
    """Write a valid brief whose contents must remain inert."""
    path = tmp_path / "fix-brief.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "change_id": _CHANGE,
                "reviewed_head_sha": _HEAD,
                "findings": [
                    {
                        "fingerprint": "b" * 24,
                        "status": "actionable",
                        "severity": "Major",
                        "path": "src/app.py",
                        "start_line": 10,
                        "end_line": 11,
                        "message": _MESSAGE,
                        "remediation": None,
                        "evidence": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_export_fix_brief_json(brief_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "findings",
            "brief",
            str(brief_path),
            "--expect-change-id",
            _CHANGE,
            "--expect-head",
            _HEAD,
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(brief_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("value", "flag"),
    [
        pytest.param("acme/app#43", "--expect-change-id", id="different-pr"),
        pytest.param("other/app#42", "--expect-change-id", id="different-repository"),
        pytest.param("c" * 40, "--expect-head", id="stale-head"),
    ],
)
def test_mismatched_context_yields_no_brief(brief_path: Path, value: str, flag: str) -> None:
    result = runner.invoke(
        app, ["findings", "brief", str(brief_path), "--format", "json", flag, value]
    )

    assert result.exit_code == 2
    assert not result.stdout
    assert "does not match" in result.stderr
    assert _MESSAGE not in result.output


def test_schema_requires_an_explicit_version(brief_path: Path) -> None:
    result = runner.invoke(app, ["findings", "brief-schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert "schema_version" in schema["required"]
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
    document = json.loads(brief_path.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)
    document.pop("schema_version")
    with pytest.raises(jsonschema.ValidationError, match="schema_version"):
        jsonschema.validate(document, schema)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("schema_version", "2.0.0", id="unsupported-version"),
        pytest.param("reviewed_head_sha", "a" * 7, id="partial-sha"),
        pytest.param("unexpected", _MESSAGE, id="unknown-field"),
    ],
)
def test_invalid_brief_does_not_echo_input(brief_path: Path, key: str, value: str) -> None:
    document = json.loads(brief_path.read_text(encoding="utf-8"))
    document[key] = value
    brief_path.write_text(json.dumps(document), encoding="utf-8")

    result = runner.invoke(app, ["findings", "brief", str(brief_path)])

    assert result.exit_code == 2
    assert not result.stdout
    assert "valid version 1.0.0 fix brief" in result.stderr
    assert "::warning::example" not in result.output
