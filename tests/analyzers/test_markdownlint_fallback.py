"""Plan 26 H3 — markdownlint fallback config via the existing absent-config patch.

Mirrors the prisma-lint fallback tests. Decisions 5-8.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.analyzers.support import import_module

_CATALOG_DIR = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "analyzers" / "catalog"
_FALLBACK_NAME = "markdownlint-default-config.json"

# Decision 6 — every filename family markdownlint reads.
_MARKDOWNLINT_CONFIG_NAMES: tuple[str, ...] = (
    ".markdownlint.json",
    ".markdownlint.yaml",
    ".markdownlint.jsonc",
    ".markdownlintrc",
    ".markdownlint-cli2.jsonc",
    ".markdownlint-cli2.json",
    ".markdownlint-cli2.yaml",
    ".markdownlint-cli2.cjs",
    ".markdownlint-cli2.mjs",
)


def _detect() -> object:
    return import_module("mergecraft.analyzers.detect")


def _resolve() -> object:
    return import_module("mergecraft.analyzers.resolve")


def _registry() -> object:
    return import_module("mergecraft.analyzers.registry")


def test_has_markdownlint_config_is_false_when_absent(tmp_path: Path) -> None:
    detect = _detect()
    assert detect.has_markdownlint_config(tmp_path) is False


@pytest.mark.parametrize("name", _MARKDOWNLINT_CONFIG_NAMES)
def test_has_markdownlint_config_recognises_each_filename_family(tmp_path: Path, name: str) -> None:
    detect = _detect()
    (tmp_path / name).write_text("{}\n", encoding="utf-8")
    assert detect.has_markdownlint_config(tmp_path) is True


def test_has_markdownlint_config_ignores_a_directory_with_the_same_name(tmp_path: Path) -> None:
    detect = _detect()
    (tmp_path / ".markdownlint.json").mkdir()
    assert detect.has_markdownlint_config(tmp_path) is False


def test_has_markdownlint_config_ignores_nested_config(tmp_path: Path) -> None:
    detect = _detect()
    nested = tmp_path / "docs"
    nested.mkdir()
    (nested / ".markdownlint.json").write_text('{"MD060": true}\n', encoding="utf-8")
    assert detect.has_markdownlint_config(tmp_path) is False


def test_has_markdownlint_config_is_exported() -> None:
    detect = _detect()
    assert "has_markdownlint_config" in detect.__all__


def test_markdownlint_default_config_disables_only_md060() -> None:
    """Decision 8 — option 2 contents; do not demote MD013 / MD024 / MD033."""
    path = _CATALOG_DIR / _FALLBACK_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["MD060"] is False
    for rule in ("MD013", "MD024", "MD033"):
        assert rule not in payload


def test_apply_config_absent_patches_injects_fallback_before_files_token(
    tmp_path: Path,
) -> None:
    resolve = _resolve()
    argv = ("markdownlint", "--json", resolve.FILES_TOKEN)
    patched, note = resolve._apply_config_absent_patches("markdownlint", tmp_path, argv)
    assert "--config" in patched
    config_idx = patched.index("--config")
    files_idx = patched.index(resolve.FILES_TOKEN)
    assert config_idx < files_idx
    assert _FALLBACK_NAME in patched[config_idx + 1]
    assert "--disable" not in patched
    assert note is not None
    assert "fallback" in note.casefold()
    assert _FALLBACK_NAME in note


@pytest.mark.parametrize("name", _MARKDOWNLINT_CONFIG_NAMES)
def test_apply_config_absent_patches_does_not_override_repo_config(
    tmp_path: Path, name: str
) -> None:
    """The repo's own config always wins — the patch fires only when absent."""
    resolve = _resolve()
    (tmp_path / name).write_text('{"MD060": true}\n', encoding="utf-8")
    argv = ("markdownlint", "--json", resolve.FILES_TOKEN)
    patched, note = resolve._apply_config_absent_patches("markdownlint", tmp_path, argv)
    assert patched == argv
    assert note is None
    assert _FALLBACK_NAME not in " ".join(patched)


def test_markdownlint_without_config_uses_conservative_fallback(tmp_path: Path) -> None:
    resolve = _resolve()
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    manifest = _registry().get_manifest("markdownlint")
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=True,
        repo_tool_path="/usr/bin/markdownlint",
        managed_available=False,
        container_available=False,
    )
    assert plan.mode != "skip"
    argv = resolve.expand_analyzer_argv(plan.argv, repo_root=tmp_path, changed_files=["README.md"])
    blob = " ".join(argv) + " " + (plan.config_note or "")
    assert "--config" in argv
    assert _FALLBACK_NAME in blob
    assert "fallback" in (plan.config_note or "").casefold()
    assert "--disable" not in argv


def test_markdownlint_with_repo_config_keeps_repo_rules(tmp_path: Path) -> None:
    resolve = _resolve()
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / ".markdownlint.json").write_text('{"MD060": true}\n', encoding="utf-8")
    manifest = _registry().get_manifest("markdownlint")
    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=tmp_path,
        repo_has_tool=True,
        repo_tool_path="/usr/bin/markdownlint",
        managed_available=False,
        container_available=False,
    )
    argv = resolve.expand_analyzer_argv(plan.argv, repo_root=tmp_path, changed_files=["README.md"])
    blob = " ".join(argv) + " " + (plan.config_note or "")
    assert _FALLBACK_NAME not in blob
    assert plan.config_note is None or "fallback" not in plan.config_note.casefold()


def test_markdownlint_fallback_note_constant_matches_prisma_pattern() -> None:
    resolve = _resolve()
    note = resolve._MARKDOWNLINT_FALLBACK_NOTE
    assert "fallback" in note.casefold()
    assert _FALLBACK_NAME in note
    assert "@catalog:" in note
