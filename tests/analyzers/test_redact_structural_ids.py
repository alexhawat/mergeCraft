"""Analyzer ids survive redaction; seeded secrets do not; distinct findings stay distinct.

Golden corpus: semgrep SARIF and trivy JSON shaped like the real tools' output,
driven through the production boundary (``redact_analyzer_output`` ->
``persist_analyzer_output`` -> ``parse_output_file``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.analyzers.parse import _redact_findings, parse_output_file, persist_analyzer_output
from mergecraft.analyzers.redact import redact_analyzer_output, redact_secrets
from mergecraft.analyzers.registry import get_manifest
from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from tests.analyzers.support import CANARY_SECRET

if TYPE_CHECKING:
    from pathlib import Path

# A random-looking credential with no known prefix: only the entropy pass catches it.
# Assembled at runtime so no credential-shaped literal sits in the tree.
_SEEDED_TOKEN = "Zq8Xw3Lm9K" + "p2Vb7Nc4Rt6Yh1"

_STRUCTURAL_TOKENS = {
    "semgrep-rule-id": "python.lang.security.audit.eval-detected",
    "ghsa-id": "GHSA-9wx4-h78v-vm56",
    "advisory-link": "https://avd.aquasec.com/nvd/cve-2024-35195",
    "rule-doc-link": "https://docs.astral.sh/ruff/rules/line-too-long",
    "bandit-test-id": "B101:assert_used",
    "pytest-node-id": "tests/test_x.py::test_foo",
    "path-line": "src/app/main.py:12",
    "purl": "pkg:pypi/requests@2.31.0",
    "image-ref": "ghcr.io/org/image:1.2.3",
    "rfc3339-offset": "2024-01-15T09:30:00+00:00",
    "rfc3339-fraction": "2024-01-15T09:30:00.123456Z",
}


@pytest.mark.parametrize("token", list(_STRUCTURAL_TOKENS.values()), ids=list(_STRUCTURAL_TOKENS))
def test_structural_analyzer_token_survives_redaction(token: str) -> None:
    assert redact_secrets(token) == token
    assert redact_secrets(f"see {token} for details") == f"see {token} for details"


@pytest.mark.parametrize(
    "text",
    [
        f"https://avd.aquasec.com/nvd/{_SEEDED_TOKEN}",
        f"python.lang.{_SEEDED_TOKEN}.audit",
        f"admin:{_SEEDED_TOKEN}@db",
        f"pkg:pypi/requests@2.31.0?token={_SEEDED_TOKEN}",
    ],
    ids=["link-path-segment", "dotted-id-part", "userinfo", "query-assignment"],
)
def test_a_secret_inside_a_structural_shape_is_still_redacted(text: str) -> None:
    out = redact_secrets(text)
    assert _SEEDED_TOKEN not in out
    assert REDACTION_SENTINEL in out


def _semgrep_sarif() -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Semgrep OSS",
                            "rules": [
                                {
                                    "id": "python.lang.security.audit.eval-detected",
                                    "defaultConfiguration": {"level": "error"},
                                    "helpUri": "https://sg.run/ZvrD",
                                },
                                {
                                    "id": "python.lang.best-practice.unspecified-open-encoding",
                                    "defaultConfiguration": {"level": "note"},
                                },
                            ],
                        }
                    },
                    "results": [
                        {
                            "ruleId": "python.lang.security.audit.eval-detected",
                            "message": {"text": f"eval of untrusted input near {CANARY_SECRET}"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/app/handler.py"},
                                        "region": {"startLine": 8},
                                    }
                                }
                            ],
                        },
                        {
                            "ruleId": "python.lang.best-practice.unspecified-open-encoding",
                            "message": {"text": f"open() without encoding; {_SEEDED_TOKEN}"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/app/handler.py"},
                                        "region": {"startLine": 12},
                                    }
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )


def _trivy_json() -> str:
    def vulnerability(advisory: str) -> dict[str, str]:
        return {
            "VulnerabilityID": advisory,
            "PkgName": "requests",
            "InstalledVersion": "2.31.0",
            "FixedVersion": "2.32.0",
            "Severity": "MEDIUM",
            "PrimaryURL": f"https://github.com/advisories/{advisory}",
            "Title": f"requests 2.31.0 is affected by {advisory} (fixed in 2.32.0)",
        }

    return json.dumps(
        {
            "SchemaVersion": 2,
            "CreatedAt": "2024-01-15T09:30:00.123456+00:00",
            "Results": [
                {
                    "Target": "requirements.txt",
                    "Vulnerabilities": [
                        vulnerability("GHSA-9wx4-h78v-vm56"),
                        vulnerability("GHSA-j8r2-6x86-q33q"),
                    ],
                }
            ],
        }
    )


def _round_trip(raw: str, *, tool_id: str, tmp_path: Path) -> tuple[str, list]:
    manifest = get_manifest(tool_id)
    redacted = redact_analyzer_output(raw, tool_id=tool_id)
    path = persist_analyzer_output(redacted, tmpdir=tmp_path / "out", tool_id=tool_id)
    return redacted, parse_output_file(path, manifest=manifest, repo_root=tmp_path)


def test_semgrep_sarif_keeps_rule_ids_and_rule_levels(tmp_path: Path) -> None:
    redacted, findings = _round_trip(_semgrep_sarif(), tool_id="semgrep", tmp_path=tmp_path)

    assert CANARY_SECRET not in redacted
    assert _SEEDED_TOKEN not in redacted
    by_rule = {finding.rule_id: finding for finding in findings}
    assert set(by_rule) == {
        "python.lang.security.audit.eval-detected",
        "python.lang.best-practice.unspecified-open-encoding",
    }
    # Each result resolves its own rule's level, not the last rule's.
    assert by_rule["python.lang.security.audit.eval-detected"].severity == "Major"
    assert by_rule["python.lang.best-practice.unspecified-open-encoding"].severity == "Trivial"
    assert "https://sg.run/ZvrD" in redacted
    assert len({finding.fingerprint for finding in findings}) == 2


def test_trivy_json_keeps_advisory_ids_and_distinct_fingerprints(tmp_path: Path) -> None:
    redacted, findings = _round_trip(_trivy_json(), tool_id="trivy", tmp_path=tmp_path)

    assert "https://github.com/advisories/GHSA-9wx4-h78v-vm56" in redacted
    assert "2024-01-15T09:30:00.123456+00:00" in redacted
    assert [finding.rule_id for finding in findings] == [
        "GHSA-9wx4-h78v-vm56",
        "GHSA-j8r2-6x86-q33q",
    ]
    assert all(finding.path == "requirements.txt" for finding in findings)
    assert len({finding.fingerprint for finding in findings}) == 2


def test_findings_whose_messages_redact_alike_keep_distinct_fingerprints() -> None:
    """The identity is fixed before message redaction, not derived from its output."""
    findings = [
        make_finding(
            tool="semgrep",
            rule_id="generic.secrets.hardcoded",
            category="Security & Privacy",
            severity="Major",
            confidence="likely",
            message=f"hardcoded credential {secret}",
            path="src/settings.py",
            start_line=3,
            end_line=3,
            source="analyzer",
        )
        for secret in (_SEEDED_TOKEN, "Hj5Tn2Wq9L" + "x4Mv8Bc3Pz7Rk6")
    ]

    redacted = _redact_findings(findings, tool_id="semgrep")

    assert {finding.message for finding in redacted} == {
        f"hardcoded credential {REDACTION_SENTINEL}"
    }
    assert redacted[0].fingerprint != redacted[1].fingerprint
