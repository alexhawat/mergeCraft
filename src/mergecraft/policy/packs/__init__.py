"""Shipped high-quality policy packs (#359).

Does not widen ``PolicyRule`` — packs validate as existing schema documents.
Fixtures are runnable by ``mergecraft policy test``.

Module: mergecraft.policy.packs
Depends: pathlib

Exports:
    Functions:
        pack_fixture_dir — Directory of should-trigger / should-not YAML fixtures.
        load_shipped_pack_rules — Parse every shipped pack into ``PolicyRule``s.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from mergecraft.policy.schema import PolicyRule, parse_rules_document

PACK_IDS: Final[tuple[str, ...]] = (
    "security",
    "public_api",
    "migrations",
    "dependency_changes",
    "authentication_authorization",
    "testing",
    "operational_readiness",
)

_PACKS_DIR: Final[Path] = Path(__file__).resolve().parent


def pack_fixture_dir() -> Path:
    """Return the directory of should-trigger / should-not pack fixtures."""
    return _PACKS_DIR / "fixtures"


def load_shipped_pack_rules() -> list[PolicyRule]:
    """Load every shipped pack YAML as existing ``PolicyRule`` documents."""
    rules: list[PolicyRule] = []
    for pack_id in PACK_IDS:
        path = _PACKS_DIR / f"{pack_id}.yaml"
        rules.extend(parse_rules_document(path.read_text(encoding="utf-8")))
    return rules


__all__ = [
    "PACK_IDS",
    "load_shipped_pack_rules",
    "pack_fixture_dir",
]
