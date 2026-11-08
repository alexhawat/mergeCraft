"""The workflow publish helpers: changelog notes and dist verification."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT

_CHANGELOG = """# Changelog

## [Unreleased]

### Added

- next thing

## [0.1.0a5] — 2026-11-10

### Added

- a shipped thing

### Fixed

- a shipped fix

## [0.1.0a4] — 2026-10-29

- old
"""


def _module(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    return importlib.import_module("release_publish")


def test_notes_are_the_body_between_this_heading_and_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module(monkeypatch)
    body = module.release_notes(_CHANGELOG, "0.1.0a5")
    assert "a shipped thing" in body
    assert "a shipped fix" in body
    assert "0.1.0a4" not in body
    assert "Unreleased" not in body


def test_an_unreleased_section_is_extractable(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    assert "next thing" in module.release_notes(_CHANGELOG, "Unreleased")


def test_a_missing_version_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    with pytest.raises(ValueError, match=r"no ## \[9.9.9\]"):
        module.release_notes(_CHANGELOG, "9.9.9")


def test_an_empty_section_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module(monkeypatch)
    text = "## [0.2.0]\n\n## [0.1.0]\n- old\n"
    with pytest.raises(ValueError, match="empty"):
        module.release_notes(text, "0.2.0")


def _dist(tmp_path: Path, *names: str) -> Path:
    directory = tmp_path / "dist"
    directory.mkdir()
    for name in names:
        (directory / name).write_bytes(b"payload")
    return directory


def test_the_wheel_and_sdist_are_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module(monkeypatch)
    directory = _dist(
        tmp_path,
        "mergecraft_action-0.1.0a5-py3-none-any.whl",
        "mergecraft_action-0.1.0a5.tar.gz",
    )
    assert [path.name for path in module.verify_dist(directory, "0.1.0a5")] == [
        "mergecraft_action-0.1.0a5-py3-none-any.whl",
        "mergecraft_action-0.1.0a5.tar.gz",
    ]


def test_an_extra_file_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module(monkeypatch)
    directory = _dist(
        tmp_path,
        "mergecraft_action-0.1.0a5-py3-none-any.whl",
        "mergecraft_action-0.1.0a5.tar.gz",
        "notes.txt",
    )
    with pytest.raises(ValueError, match="exactly one wheel and one sdist"):
        module.verify_dist(directory, "0.1.0a5")


def test_a_missing_sdist_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module(monkeypatch)
    directory = _dist(tmp_path, "mergecraft_action-0.1.0a5-py3-none-any.whl")
    with pytest.raises(ValueError, match="exactly one wheel and one sdist"):
        module.verify_dist(directory, "0.1.0a5")


def test_another_versions_artifact_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module(monkeypatch)
    directory = _dist(
        tmp_path,
        "mergecraft_action-0.1.0a4-py3-none-any.whl",
        "mergecraft_action-0.1.0a4.tar.gz",
    )
    with pytest.raises(ValueError, match=r"names version 0\.1\.0a4, not 0\.1\.0a5"):
        module.verify_dist(directory, "0.1.0a5")


def test_cli_notes_and_verify_dist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module(monkeypatch)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    assert module.main(["notes", "--changelog", str(changelog), "--version", "0.1.0a5"]) == 0
    directory = _dist(
        tmp_path,
        "mergecraft_action-0.1.0a5-py3-none-any.whl",
        "mergecraft_action-0.1.0a5.tar.gz",
    )
    assert module.main(["verify-dist", "--dist", str(directory), "--version", "0.1.0a5"]) == 0
    assert module.main(["notes", "--changelog", str(changelog), "--version", "9.9.9"]) == 1


def test_an_alpha_dist_is_not_accepted_for_the_stable_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A substring check would accept 0.1.0a5 for 0.1.0."""
    module = _module(monkeypatch)
    directory = _dist(
        tmp_path,
        "mergecraft_action-0.1.0a5-py3-none-any.whl",
        "mergecraft_action-0.1.0a5.tar.gz",
    )
    with pytest.raises(ValueError, match=r"names version 0\.1\.0a5, not 0\.1\.0"):
        module.verify_dist(directory, "0.1.0")
