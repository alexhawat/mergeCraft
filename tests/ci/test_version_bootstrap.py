"""Version bootstrap keeps build provenance without loading application settings."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft import build_metadata
from mergecraft.config.env import RunInputsEnv
from tests.docs.support import load_script_module

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clear_build_identity_cache() -> Iterator[None]:
    build_metadata.resolve_build_commit.cache_clear()
    yield
    build_metadata.resolve_build_commit.cache_clear()


@pytest.mark.parametrize("baked", [None, "b" * 40], ids=["source", "wheel"])
@pytest.mark.parametrize(
    ("primary", "fallback"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        (" aaaa ", None),
        (None, " dddd "),
        ("", " dddd "),
        ("  ", " dddd "),
        (" aaaa ", "dddd"),
    ],
    ids=[
        "unset",
        "empty",
        "whitespace",
        "value",
        "field-fallback",
        "empty-fallback",
        "whitespace-primary",
        "alias-priority",
    ],
)
def test_build_identity_matches_typed_environment_semantics(
    monkeypatch: pytest.MonkeyPatch, primary: str | None, fallback: str | None, baked: str | None
) -> None:
    for name, value in (("MERGECRAFT_BUILD_COMMIT", primary), ("build_commit", fallback)):
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(build_metadata, "_baked_commit", baked)
    monkeypatch.setattr(build_metadata, "_git_head_commit", lambda _root: "c" * 40)
    expected = RunInputsEnv().build_commit or baked or "c" * 40
    assert build_metadata.resolve_build_commit() == expected


def test_version_entrypoint_does_not_load_pydantic(tmp_path: Path) -> None:
    script = """
import sys
from mergecraft.cli.entrypoint import main
sys.argv = ['mergecraft', '--version']
main()
assert 'pydantic' not in sys.modules
assert 'pydantic_settings' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path), "MERGECRAFT_BUILD_COMMIT": "a" * 40},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "aaaaaaa" in result.stdout


def test_generated_environment_example_explains_build_provenance() -> None:
    generator = load_script_module("scripts/gen_env_example.py")
    rendered = generator.render()
    assert "# Build provenance: MERGECRAFT_BUILD_COMMIT" in rendered
    assert "# The existing build_commit compatibility alias" in rendered
    assert "# MERGECRAFT_BUILD_COMMIT=" not in rendered
