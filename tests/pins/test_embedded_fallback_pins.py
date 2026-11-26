"""The embedded minimal Action pin matches the canonical defaults (#1594).

An install with neither ``scripts/example_workflows/defaults.yaml`` nor the
packaged copy falls back to ``_FALLBACK_DEFAULTS`` in ``mergecraft.pins``. That
copy must name the same release tag and commit as the canonical defaults, and
``make pins-check`` must fail when it does not.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from mergecraft import pins as runtime_pins
from scripts import check_example_defaults_sync as pins_check
from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_CANONICAL = REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"
_PINS_SOURCE = REPO_ROOT / "src" / "mergecraft" / "pins.py"


def _canonical() -> dict[str, str]:
    raw = yaml.safe_load(_CANONICAL.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return {str(key): str(value) for key, value in raw.items()}


@pytest.fixture
def fresh_loader(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No example-pin env overrides and no cached defaults, before and after."""
    for name in list(os.environ):
        if name.startswith("MERGECRAFT_EXAMPLE_"):
            monkeypatch.delenv(name)
    runtime_pins.load_example_defaults.cache_clear()
    yield
    runtime_pins.load_example_defaults.cache_clear()


@pytest.mark.usefixtures("fresh_loader")
def test_fallback_pair_matches_the_canonical_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither defaults file is present: the embedded fallback is what loads."""
    monkeypatch.setattr(runtime_pins, "_CHECKOUT_DEFAULTS_PATH", tmp_path / "absent.yaml")
    monkeypatch.setattr(runtime_pins, "files", lambda _package: tmp_path)
    canonical = _canonical()

    assert runtime_pins.action_pin_minimal() == canonical["action_pin_minimal"]
    assert runtime_pins.action_sha_minimal() == canonical["action_sha_minimal"]
    assert runtime_pins.load_example_defaults() == canonical


@pytest.mark.usefixtures("fresh_loader")
def test_packaged_defaults_path_matches_the_canonical_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: an installed wheel with package data reads the packaged copy."""
    monkeypatch.setattr(runtime_pins, "_CHECKOUT_DEFAULTS_PATH", tmp_path / "absent.yaml")
    assert runtime_pins._packaged_defaults() is not None
    canonical = _canonical()

    assert runtime_pins.action_pin_minimal() == canonical["action_pin_minimal"]
    assert runtime_pins.action_sha_minimal() == canonical["action_sha_minimal"]


def test_pins_check_accepts_the_embedded_fallback() -> None:
    assert pins_check._check_embedded_fallback(pins_check._load(_CANONICAL)) == []


@pytest.mark.parametrize(
    ("key", "stale"),
    [
        ("action_pin_minimal", "v0.1.0a1"),
        ("action_sha_minimal", "521c0aedbf525a80a5bf6eddf0119ada85a8d381"),
    ],
)
def test_pins_check_fails_when_only_the_embedded_pair_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, stale: str
) -> None:
    canonical: dict[str, Any] = pins_check._load(_CANONICAL)
    source = _PINS_SOURCE.read_text(encoding="utf-8")
    current = f'"{key}": "{canonical[key]}"'
    assert source.count(current) == 1
    drifted = tmp_path / "src" / "mergecraft" / "pins.py"
    drifted.parent.mkdir(parents=True)
    drifted.write_text(source.replace(current, f'"{key}": "{stale}"'), encoding="utf-8")
    monkeypatch.setattr(pins_check, "REPO", tmp_path)
    monkeypatch.setattr(pins_check, "EMBEDDED_FALLBACK", drifted)

    failures = pins_check._check_embedded_fallback(canonical)

    assert failures == [
        f"src/mergecraft/pins.py _FALLBACK_DEFAULTS[{key!r}] is {stale!r}, "
        f"defaults.yaml has {canonical[key]!r}"
    ]
