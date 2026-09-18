"""Plan 26 H3 / P7 — trufflehog excludes virtualenvs; fixtures suppressed by name.

Decision 9a: no blanket ``tests/**`` skip. A newly committed secret in a test still fires.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.analyzers.support import import_module

# Observed noise on run 34542726646 — each exemption names why, not a path glob.
_NAMED_FIXTURES: tuple[tuple[str, str], ...] = (
    (
        "tests/analyzers/fixtures/repo/config/planted-secret.env",
        "planted-secret",
    ),
    (
        "tests/tracing/test_redact_url.py",
        "redact",
    ),
    (
        "tests/security/test_credentials.py",
        "credential",
    ),
    (
        "tests/scripts/test_native_output_to_sarif.py",
        "sarif",
    ),
)
_UNNAMED_TEST_SECRET = "tests/new_committed_secret.env"
_H5_EMIT_XFAIL = pytest.mark.xfail(
    reason="green after H5 remediations: CI SARIF named-fixture suppressions",
    strict=False,
)


def _config() -> object:
    return import_module("mergecraft.analyzers.config")


def _ci_sarif() -> object:
    return import_module("scripts.ci_extended_sarif")


def test_trufflehog_exclude_paths_cover_venv_dev_and_virtualenv_trees(
    tmp_path: Path,
) -> None:
    module = _ci_sarif()
    path = module.write_trufflehog_exclude_paths(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert ".venv-dev" in text
    assert r"\.venv/" in text or ".venv/" in text
    assert "site-packages" in text or "virtualenv" in text.casefold()


def test_trufflehog_exclude_paths_do_not_blanket_skip_tests(tmp_path: Path) -> None:
    module = _ci_sarif()
    path = module.write_trufflehog_exclude_paths(tmp_path)
    text = path.read_text(encoding="utf-8")
    for forbidden in ("^tests/", "tests/**", r"tests/\*\*"):
        assert forbidden not in text.splitlines()
    assert not any(line.strip() in {"tests/", "tests/**"} for line in text.splitlines())


def test_trufflehog_named_fixture_suppressions_cover_each_intentional_fixture() -> None:
    config = _config()
    suppressions = dict(config.trufflehog_named_fixture_suppressions())
    for path, needle in _NAMED_FIXTURES:
        assert path in suppressions, f"missing named suppression for {path}"
        reason = suppressions[path]
        assert reason.strip(), f"suppression for {path} must name why it is exempt"
        assert needle.casefold() in reason.casefold()


def test_named_fixture_is_suppressed_and_a_new_test_secret_is_not() -> None:
    config = _config()
    planted = "tests/analyzers/fixtures/repo/config/planted-secret.env"
    assert config.is_trufflehog_path_suppressed(planted) is True
    assert config.is_trufflehog_path_suppressed("tests/new_committed_secret.env") is False
    assert config.is_trufflehog_path_suppressed("tests/security/test_unrelated.py") is False


def test_virtualenv_tree_is_out_of_trufflehog_scope() -> None:
    config = _config()
    assert (
        config.is_trufflehog_path_suppressed(
            ".venv-dev/lib/python3.14/site-packages/httpx/_urls.py"
        )
        is True
    )
    assert config.is_trufflehog_path_suppressed("src/mergecraft/cli/app.py") is False


def _named_fixture_paths() -> tuple[str, ...]:
    return tuple(path for path, _needle in _NAMED_FIXTURES)


def _thog_finding_line(path: str) -> str:
    return json.dumps(
        {
            "SourceMetadata": {"Data": {"Filesystem": {"file": path, "line": 1}}},
            "DetectorName": "AWSAccessKey",
            "Verified": False,
            "Raw": "PLANTED_NOT_A_REAL_SECRET",
        }
    )


def _sarif_uris(doc: dict[str, Any]) -> set[str]:
    results = doc["runs"][0]["results"]
    return {item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for item in results}


def _emit_trufflehog_with_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paths: tuple[str, ...],
) -> dict[str, Any]:
    module = _ci_sarif()
    stdout = "\n".join(_thog_finding_line(path) for path in paths) + "\n"
    monkeypatch.setattr(module, "_trufflehog_scan_argv", lambda **_kwargs: ["trufflehog"])
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["trufflehog"], returncode=0, stdout=stdout, stderr=""
        ),
    )
    out = tmp_path / "trufflehog.sarif"
    module.emit_trufflehog_sarif(out=out, repo_root=tmp_path)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@_H5_EMIT_XFAIL
def test_emit_trufflehog_sarif_drops_named_fixture_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-D9a — CI emit applies the same named suppressions as the adapter path."""
    named = _named_fixture_paths()
    uris = _sarif_uris(_emit_trufflehog_with_paths(tmp_path, monkeypatch, named))
    for path in named:
        assert path not in uris, f"CI SARIF still emits named fixture {path}"


@_H5_EMIT_XFAIL
def test_emit_trufflehog_sarif_named_suppressions_do_not_blanket_skip_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-D9a — a newly committed secret under tests/ still fires; no tests/** skip."""
    named = _named_fixture_paths()
    uris = _sarif_uris(
        _emit_trufflehog_with_paths(tmp_path, monkeypatch, (*named, _UNNAMED_TEST_SECRET))
    )
    assert _UNNAMED_TEST_SECRET in uris
    for path in named:
        assert path not in uris, f"CI SARIF still emits named fixture {path}"
