"""Analyzer finding identity does not depend on where the repo is checked out (#1322)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from mergecraft.analyzers.adapters import _normalize_paths
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers import get_parser
from mergecraft.analyzers.parsers.buf_native import (
    parse_buf_breaking_json,
    parse_buf_lint_json,
)
from mergecraft.analyzers.registry import get_manifest
from mergecraft.review_taxonomy import finding_fingerprint


def _ruff_raw(filename: str) -> str:
    return json.dumps(
        [
            {
                "filename": filename,
                "location": {"row": 3, "column": 1},
                "message": "`os` imported but unused",
                "code": "F401",
                "severity": "error",
            }
        ]
    )


def test_ruff_fingerprint_is_the_same_from_two_checkout_roots(tmp_path: Path) -> None:
    """Regression: absolute ruff filenames are hashed repo-relative."""
    parse = get_parser("ruff_json")
    manifest = get_manifest("ruff")
    fingerprints = set()
    for root in (tmp_path / "ci" / "workspace", tmp_path / "home" / "dev" / "repo"):
        (root / "src").mkdir(parents=True)
        (finding,) = parse(_ruff_raw(str(root / "src" / "r.py")), manifest=manifest, repo_root=root)
        assert finding.path == "src/r.py"
        fingerprints.add(finding.fingerprint)
    assert fingerprints == {finding_fingerprint(path="src/r.py", body="`os` imported but unused")}


def _buf_line(path: str) -> str:
    return json.dumps(
        {"path": path, "start_line": 4, "type": "FIELD_NO_DELETE", "message": "Field 1 deleted."}
    )


@pytest.mark.parametrize(
    "parse",
    [parse_buf_breaking_json, parse_buf_lint_json],
    ids=["breaking", "lint"],
)
def test_buf_fingerprint_is_the_same_from_two_checkout_roots(
    parse: Callable[..., list[Finding]], tmp_path: Path
) -> None:
    """Regression: absolute and root-relative buf paths resolve against the repo root."""
    manifest = get_manifest("buf")
    identities = set()
    for root in (tmp_path / "ci" / "workspace", tmp_path / "home" / "dev" / "repo"):
        (root / "proto").mkdir(parents=True)
        for path in (str(root / "proto" / "x.proto"), "proto/x.proto"):
            (finding,) = parse(_buf_line(path), manifest=manifest, repo_root=root)
            assert finding.path == "proto/x.proto"
            identities.add(finding.fingerprint)
    assert len(identities) == 1


def test_buf_out_of_root_path_is_not_shortened_to_basename(tmp_path: Path) -> None:
    """An out-of-root path keeps its form instead of aliasing a root-level file."""
    root = tmp_path / "repo"
    root.mkdir()
    outside = str(tmp_path / "elsewhere" / "x.proto")
    (finding,) = parse_buf_lint_json(
        _buf_line(outside), manifest=get_manifest("buf"), repo_root=root
    )
    assert finding.path == outside


def test_normalize_paths_restamps_default_fingerprint(tmp_path: Path) -> None:
    """Defensive: rewriting an absolute path also recomputes the derived fingerprint."""
    absolute = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="possible",
        message="unused import",
        path=str(tmp_path / "a.py"),
        start_line=1,
        end_line=1,
        source="analyzer",
    )
    pinned = absolute.model_copy(update={"fingerprint": "pinned-by-parser"})
    restamped, kept = _normalize_paths([absolute, pinned], repo_root=tmp_path)
    assert restamped.path == "a.py"
    assert restamped.fingerprint == finding_fingerprint(path="a.py", body="unused import")
    assert kept.fingerprint == "pinned-by-parser"
