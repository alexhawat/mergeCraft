"""``scripts/security_sweep_report.py`` — the scheduled sweep's issue body (#1069).

The sweep files one tracking issue fingerprinted by its advisory IDs. These
tests pin the parsing of each tool report, the fingerprint's stability, the
body's marker and columns, and that a missing report is ``incomplete`` rather
than ``clear`` — a sweep that could not look must never close a live alert.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "security_sweep_report.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("security_sweep_report", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sweep = _load()

_PIP_AUDIT_CLEAN: dict[str, Any] = {
    "dependencies": [{"name": "annotated-doc", "version": "0.0.4", "vulns": []}],
    "fixes": [],
}
_PIP_AUDIT_FINDINGS: dict[str, Any] = {
    "dependencies": [
        {
            "name": "certifi",
            "version": "2026.1.1",
            "vulns": [
                {
                    "id": "PYSEC-2026-4320",
                    "fix_versions": ["2026.10.5"],
                    "aliases": ["CVE-2026-1"],
                    "description": "bad root",
                }
            ],
        },
        {
            "name": "msgpack",
            "version": "1.1.0",
            "vulns": [{"id": "CVE-2026-114613", "fix_versions": [], "aliases": []}],
        },
        {"name": "mergecraft-action", "skip_reason": "not on PyPI"},
    ],
    "fixes": [],
}
_BANDIT_CLEAN: dict[str, Any] = {"results": [], "errors": []}
_TRIVY_CLEAN: dict[str, Any] = {
    "Metadata": {"RepoDigests": ["ghcr.io/alexhawat/mergecraft@sha256:" + "a" * 64]},
    "Results": [{"Target": "debian", "Vulnerabilities": None}],
}
_TRIVY_FINDINGS: dict[str, Any] = {
    "Metadata": {"RepoDigests": ["ghcr.io/alexhawat/mergecraft@sha256:" + "b" * 64]},
    "Results": [
        {
            "Target": "debian",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2026-84782",
                    "PkgName": "libssl3",
                    "InstalledVersion": "3.0.1",
                    "FixedVersion": "3.0.2",
                    "Severity": "HIGH",
                }
            ],
        }
    ],
}


def _write(tmp_path: Path, name: str, document: Any) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _run(
    tmp_path: Path,
    *,
    pip_audit: Any = _PIP_AUDIT_CLEAN,
    bandit: Any = _BANDIT_CLEAN,
    lockcheck: str = "pass",
    latest: Any = _TRIVY_CLEAN,
    analyzers: Any = _TRIVY_CLEAN,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, str], Path]:
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    body = tmp_path / "body.md"
    args = [
        "--pip-audit",
        str(_write(tmp_path, "pip-audit.json", pip_audit) if pip_audit is not None else "x"),
        "--bandit",
        str(_write(tmp_path, "bandit.json", bandit)),
        "--lockcheck",
        lockcheck,
        "--image",
        f":latest={_write(tmp_path, 'trivy-latest.json', latest)}",
        "--image",
        f":analyzers={_write(tmp_path, 'trivy-analyzers.json', analyzers)}",
        "--run-url",
        "https://example.invalid/run/1",
        "--body-out",
        str(body),
    ]
    assert sweep.main(args) == 0
    outputs = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if line
    )
    return outputs, body


def test_parse_pip_audit_reports_package_versions_and_advisory() -> None:
    found = sweep.parse_pip_audit(_PIP_AUDIT_FINDINGS)
    assert [(a.package, a.installed, a.fixed, a.advisory_id) for a in found] == [
        ("certifi", "2026.1.1", "2026.10.5", "PYSEC-2026-4320"),
        ("msgpack", "1.1.0", "none published", "CVE-2026-114613"),
    ]


def test_parse_pip_audit_rejects_a_foreign_shape() -> None:
    with pytest.raises(sweep.ReportError):
        sweep.parse_pip_audit({"vulnerabilities": []})


def test_parse_trivy_reports_os_package_findings_and_tolerates_null_lists() -> None:
    found = sweep.parse_trivy(_TRIVY_FINDINGS, ":latest")
    assert [(a.source, a.package, a.fixed, a.advisory_id) for a in found] == [
        ("image :latest", "libssl3", "3.0.2", "CVE-2026-84782")
    ]
    assert sweep.parse_trivy(_TRIVY_CLEAN, ":latest") == []
    assert sweep.trivy_digest(_TRIVY_FINDINGS).endswith("b" * 64)


def test_parse_bandit_turns_each_result_into_a_failure() -> None:
    found = sweep.parse_bandit(
        {
            "results": [
                {
                    "test_id": "B602",
                    "filename": "src/mergecraft/x.py",
                    "line_number": 7,
                    "issue_text": "shell=True",
                }
            ]
        }
    )
    assert [item.finding_id for item in found] == ["bandit:B602:src/mergecraft/x.py"]
    assert "src/mergecraft/x.py:7" in found[0].detail


def test_fingerprint_is_stable_across_order_and_duplicates() -> None:
    first = sweep.fingerprint(["CVE-2", "PYSEC-1", "CVE-2"])
    assert first == sweep.fingerprint(["PYSEC-1", "CVE-2"])
    assert first != sweep.fingerprint(["PYSEC-1"])
    assert len(first) == 64


def test_a_clean_sweep_is_clear_and_writes_no_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs, body = _run(tmp_path, monkeypatch=monkeypatch)
    assert outputs == {"status": "clear", "fingerprint": "", "count": "0"}
    assert not body.exists()


def test_findings_render_one_body_with_the_marker_and_every_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs, body = _run(
        tmp_path,
        pip_audit=_PIP_AUDIT_FINDINGS,
        latest=_TRIVY_FINDINGS,
        analyzers=_TRIVY_FINDINGS,
        monkeypatch=monkeypatch,
    )
    ids = ["CVE-2026-114613", "CVE-2026-84782", "PYSEC-2026-4320"]
    assert outputs["status"] == "findings"
    assert outputs["count"] == "3", "the same CVE on both images is one advisory ID"
    assert outputs["fingerprint"] == sweep.fingerprint(ids)
    text = body.read_text(encoding="utf-8")
    assert text.splitlines()[0] == f"<!-- security-sweep:{sweep.fingerprint(ids)} -->"
    assert "| `certifi` | 2026.1.1 | 2026.10.5 | PYSEC-2026-4320 |" in text
    assert "| `msgpack` | 1.1.0 | none published | CVE-2026-114613 |" in text
    assert "| :latest | `libssl3` | 3.0.1 | 3.0.2 | CVE-2026-84782 |" in text
    assert "| :analyzers | `libssl3` | 3.0.1 | 3.0.2 | CVE-2026-84782 |" in text
    assert "make lockcheck" in text
    assert "make security" in text


def test_the_same_findings_fingerprint_identically_on_a_later_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = []
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        outputs, _ = _run(directory, pip_audit=_PIP_AUDIT_FINDINGS, monkeypatch=monkeypatch)
        runs.append(outputs["fingerprint"])
    assert runs[0] == runs[1]


def test_a_stale_lockfile_and_a_bandit_finding_are_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs, body = _run(
        tmp_path,
        lockcheck="fail",
        bandit={"results": [{"test_id": "B602", "filename": "a.py", "line_number": 1}]},
        monkeypatch=monkeypatch,
    )
    assert outputs["status"] == "findings"
    assert outputs["count"] == "2"
    text = body.read_text(encoding="utf-8")
    assert "`make lockcheck` fails" in text
    assert "bandit `B602`" in text


def test_a_missing_report_is_incomplete_never_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs, body = _run(tmp_path, pip_audit=None, monkeypatch=monkeypatch)
    assert outputs["status"] == "incomplete"
    assert not body.exists()
    assert "pip-audit" in capsys.readouterr().out


@pytest.mark.parametrize("lockcheck", ["missing", ""])
def test_an_unrecorded_lockcheck_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lockcheck: str
) -> None:
    outputs, _ = _run(tmp_path, lockcheck=lockcheck, monkeypatch=monkeypatch)
    assert outputs["status"] == "incomplete"


def test_an_unparseable_trivy_report_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs, _ = _run(tmp_path, latest=["not", "an", "object"], monkeypatch=monkeypatch)
    assert outputs["status"] == "incomplete"
