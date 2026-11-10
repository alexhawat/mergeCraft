"""W0.4-3 — scanner waivers expire, and a seeded finding fails each blocking scanner."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import ci_extended_sarif, ci_npm_audit_gate, scanner_waivers

# The scripts import ``scanner_waivers`` as a top-level module (they run as files),
# which is a different module object from ``scripts.scanner_waivers``. Patch that one.
_SCRIPT_DIR = str(Path(scanner_waivers.__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import scanner_waivers as script_waivers  # noqa: E402


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _write(file: Path, *, scanner: str = "semgrep", rule: str = "r1", **overrides: object) -> Path:
    entry: dict[str, object] = {
        "scanner": scanner,
        "rule": rule,
        "justification": "accepted: mitigated elsewhere",
        "expires": (_today() + timedelta(days=30)).isoformat(),
    }
    entry.update(overrides)
    lines = ["[[waiver]]"]
    for key, value in entry.items():
        if value is None:
            continue
        lines.append(f'{key} = "{value}"')
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file


def test_shipped_waiver_file_is_valid_and_empty() -> None:
    assert scanner_waivers.main([]) == 0
    assert scanner_waivers.load_waivers() == []


def test_valid_waiver_loads_and_matches_by_rule_and_path_glob(tmp_path: Path) -> None:
    waivers = scanner_waivers.load_waivers(_write(tmp_path / "w.toml", path="src/a/*.py"))
    assert scanner_waivers.is_waived(waivers, scanner="semgrep", rule="r1", path="src/a/x.py")
    assert not scanner_waivers.is_waived(waivers, scanner="semgrep", rule="r1", path="src/b/x.py")
    assert not scanner_waivers.is_waived(waivers, scanner="semgrep", rule="r2", path="src/a/x.py")
    assert not scanner_waivers.is_waived(
        waivers, scanner="trufflehog", rule="r1", path="src/a/x.py"
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"expires": "2000-01-01"}, "expired on 2000-01-01"),
        ({"expires": None}, "missing or malformed expires"),
        ({"expires": "soon"}, "missing or malformed expires"),
        ({"justification": None}, "missing justification"),
        ({"justification": "  "}, "missing justification"),
        ({"scanner": "bandit"}, "scanner must be one of"),
        ({"expires": "2099-01-01"}, "more than 90 days out"),
    ],
)
def test_invalid_or_expired_waiver_fails_validation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, object],
    message: str,
) -> None:
    path = _write(tmp_path / "w.toml", **overrides)
    assert scanner_waivers.main([str(path)]) == 1
    assert message in capsys.readouterr().err
    with pytest.raises(ValueError, match=message):
        scanner_waivers.load_waivers(path)


def test_native_toml_date_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "w.toml"
    expires = (_today() + timedelta(days=10)).isoformat()
    path.write_text(
        f'[[waiver]]\nscanner = "npm-audit"\nrule = "left-pad"\njustification = "x"\n'
        f"expires = {expires}\n",
        encoding="utf-8",
    )
    assert scanner_waivers.main([str(path)]) == 0


def _sarif(*results: tuple[str, str]) -> dict[str, Any]:
    return {
        "version": "2.1.0",
        "runs": [
            {
                "results": [
                    {
                        "ruleId": rule,
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}],
                    }
                    for rule, uri in results
                ]
            }
        ],
    }


def _stub_emitter(monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]) -> None:
    def emit(*, out: Path, **_: object) -> None:
        out.write_text(json.dumps(document), encoding="utf-8")

    monkeypatch.setitem(ci_extended_sarif._EMITTERS, "semgrep", emit)
    monkeypatch.setitem(ci_extended_sarif._EMITTERS, "trufflehog", emit)


@pytest.mark.parametrize("tool", ["semgrep", "trufflehog"])
def test_seeded_finding_fails_the_scan_but_still_writes_the_sarif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tool: str
) -> None:
    _stub_emitter(monkeypatch, _sarif(("seeded.rule", "src/mergecraft/x.py")))
    out = tmp_path / "out.sarif"
    argv = ["--fail-on-findings", tool, str(out)]
    assert ci_extended_sarif.main(argv) == 1
    assert out.is_file()
    assert "seeded.rule src/mergecraft/x.py" in capsys.readouterr().err


def test_without_the_flag_findings_stay_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_emitter(monkeypatch, _sarif(("seeded.rule", "src/x.py")))
    assert ci_extended_sarif.main(["semgrep", str(tmp_path / "out.sarif")]) == 0


def test_clean_scan_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_emitter(monkeypatch, _sarif())
    assert ci_extended_sarif.main(["--fail-on-findings", str(tmp_path / "out.sarif")]) == 0


def test_waived_finding_passes_until_the_waiver_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waivers = _write(tmp_path / "w.toml", rule="seeded.rule", path="src/*")
    document = _sarif(("seeded.rule", "src/x.py"))
    assert (
        ci_extended_sarif.unwaived_findings(document, scanner="semgrep", waivers_path=waivers) == []
    )
    expired = _write(tmp_path / "e.toml", rule="seeded.rule", expires="2000-01-01")
    with pytest.raises(ValueError, match="expired"):
        ci_extended_sarif.unwaived_findings(document, scanner="semgrep", waivers_path=expired)
    _stub_emitter(monkeypatch, document)
    monkeypatch.setattr(script_waivers, "DEFAULT_PATH", expired)
    assert ci_extended_sarif.main(["--fail-on-findings", str(tmp_path / "o.sarif")]) == 1


def _audit(**packages: tuple[str, list[object]]) -> dict[str, Any]:
    return {
        "vulnerabilities": {
            name: {"name": name, "severity": severity, "via": via}
            for name, (severity, via) in packages.items()
        }
    }


_ADVISORY = {"source": 1, "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"}


def test_npm_audit_gate_blocks_high_and_passes_moderate(tmp_path: Path) -> None:
    report = tmp_path / "audit.json"
    waivers = tmp_path / "none.toml"
    report.write_text(json.dumps(_audit(pkg=("high", [_ADVISORY]))), encoding="utf-8")
    assert ci_npm_audit_gate.main(["--input", str(report), "--waivers", str(waivers)]) == 1
    report.write_text(json.dumps(_audit(pkg=("moderate", [_ADVISORY]))), encoding="utf-8")
    assert ci_npm_audit_gate.main(["--input", str(report), "--waivers", str(waivers)]) == 0


def test_npm_audit_gate_honours_an_unexpired_advisory_waiver(tmp_path: Path) -> None:
    report = tmp_path / "audit.json"
    report.write_text(json.dumps(_audit(pkg=("critical", [_ADVISORY]))), encoding="utf-8")
    waiver = _write(tmp_path / "w.toml", scanner="npm-audit", rule="GHSA-aaaa-bbbb-cccc")
    assert ci_npm_audit_gate.main(["--input", str(report), "--waivers", str(waiver)]) == 0
    expired = _write(
        tmp_path / "x.toml", scanner="npm-audit", rule="GHSA-aaaa-bbbb-cccc", expires="2000-01-01"
    )
    assert ci_npm_audit_gate.main(["--input", str(report), "--waivers", str(expired)]) == 1


def test_npm_audit_gate_fails_closed_without_a_report(tmp_path: Path) -> None:
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({"error": {"summary": "offline"}}), encoding="utf-8")
    assert (
        ci_npm_audit_gate.main(["--input", str(report), "--waivers", str(tmp_path / "n.toml")]) == 1
    )
    report.write_text("not json", encoding="utf-8")
    assert (
        ci_npm_audit_gate.main(["--input", str(report), "--waivers", str(tmp_path / "n.toml")]) == 1
    )
