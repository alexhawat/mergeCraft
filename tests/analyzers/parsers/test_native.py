"""Native JSON parsers — recorded fixtures only, never shell out (D3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.analyzers.support import FIXTURES_DIR, import_module


@pytest.mark.parametrize(
    ("parser_id", "fixture"),
    [
        ("ruff_json", "native/ruff-minimal.json"),
        ("shellcheck_json", "native/shellcheck-minimal.json"),
    ],
)
def test_native_parser_recorded_fixture(parser_id: str, fixture: str) -> None:
    parsers = import_module("mergecraft.analyzers.parsers")
    manifest = import_module("mergecraft.analyzers.manifest")
    raw = (FIXTURES_DIR / fixture).read_text(encoding="utf-8")
    m = manifest.load_manifest_yaml(
        f"""
id: test-{parser_id}
category: lint
languages: []
detect:
  files: ["*"]
command: ["noop"]
scope: diff
parser: {parser_id}
supports_fix: false
default_enabled: false
version: "0.0.0"
runtime: managed
timeout_s: 60
trust: untrusted
severity_map:
  error: Major
  warning: Minor
provenance: {{}}
network_allowlist: []
exclusive_group: test
"""
    )
    parse = parsers.get_parser(parser_id)
    findings = parse(raw, manifest=m, repo_root=Path("."))
    assert findings
    assert findings[0].path


def test_parsers_never_shell_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def _boom(*args: object, **kwargs: object) -> None:
        msg = "parser tests must not shell out"
        raise AssertionError(msg)

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    parsers = import_module("mergecraft.analyzers.parsers")
    raw = (FIXTURES_DIR / "native/ruff-minimal.json").read_text(encoding="utf-8")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_yaml(
        """
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
    )
    findings = parsers.get_parser("ruff_json")(raw, manifest=m, repo_root=Path("."))
    assert findings


def test_trivy_parser_tolerates_leading_log_noise() -> None:
    """Trivy may print a timestamped INFO line before the JSON object."""
    parsers = import_module("mergecraft.analyzers.parsers")
    manifest = import_module("mergecraft.analyzers.manifest")
    body = (FIXTURES_DIR / "native/trivy-minimal.json").read_text(encoding="utf-8")
    raw = "2026-08-01T08:13:17.574Z\tINFO\tLoaded config\n" + body
    m = manifest.load_manifest_yaml(
        """
id: trivy
category: vuln
languages: []
detect:
  files: ["requirements*.txt"]
command: ["trivy", "fs", "--quiet", "--format", "json"]
scope: diff
parser: trivy_json
supports_fix: false
default_enabled: false
version: "0.72.0"
runtime: managed
timeout_s: 300
trust: untrusted
severity_map:
  critical: Critical
  high: Major
  medium: Minor
  low: Trivial
  unknown: Minor
provenance: {}
network_allowlist: []
exclusive_group: dependency-vuln
"""
    )
    findings = parsers.get_parser("trivy_json")(raw, manifest=m, repo_root=Path("."))
    assert findings
    assert findings[0].rule_id == "CVE-2024-0001"
