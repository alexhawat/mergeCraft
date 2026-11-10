"""ruff reports ``severity: error`` for every diagnostic; the rule code decides."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.analyzers.support import import_module

_MANIFEST = """
id: ruff
category: lint
languages: [python]
detect:
  files: ["*.py"]
command: ["ruff", "check"]
scope: diff
parser: ruff_json
supports_fix: false
default_enabled: false
version: "0.15.12"
runtime: repo-native
timeout_s: 120
trust: trusted
severity_map:
  error: Major
  warning: Minor
provenance: {}
network_allowlist: []
exclusive_group: python-lint
"""


def _parse(code: str, severity: str = "error") -> str:
    parsers = import_module("mergecraft.analyzers.parsers")
    manifest = import_module("mergecraft.analyzers.manifest").load_manifest_yaml(_MANIFEST)
    raw = json.dumps(
        [
            {
                "filename": "src/a.py",
                "location": {"row": 1, "column": 1},
                "message": "m",
                "code": code,
                "severity": severity,
            }
        ]
    )
    findings = parsers.get_parser("ruff_json")(raw, manifest=manifest, repo_root=Path())
    return findings[0].severity


@pytest.mark.parametrize(
    "code",
    ["F821", "F822", "F823", "F811", "E999", "E902", "B006", "S101", "PLE0604", "ASYNC100"],
)
def test_bug_class_rules_stay_major(code: str) -> None:
    assert _parse(code) == "Major"


@pytest.mark.parametrize(
    "code",
    [
        "F401",
        "F841",
        "F541",
        "E501",
        "W291",
        "I001",
        "D100",
        "N802",
        "UP006",
        "Q000",
        "COM812",
        "SIM101",
        "SLF001",
        "SLOT000",
        "BLE001",
    ],
)
def test_style_rules_are_minor_even_when_ruff_says_error(code: str) -> None:
    assert _parse(code) == "Minor"


def test_native_warning_never_escalates() -> None:
    assert _parse("F821", severity="warning") == "Minor"
