"""Documented provider-auth examples name labels that ``mergecraft init`` seeds.

The docs previously led with Claude and listed labels ``init`` never writes
(``cursor``, ``nous``), so an operator following them hit "not a registered
provider". These tests pin the examples to the real seeded roster and the real
CLI scopes.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from mergecraft.config.settings import RepoSettings
from mergecraft.models import PROVIDERS

_ROOT = Path(__file__).resolve().parents[2]
_DOCS = (
    "README.md",
    "AGENTS-mergecraft.md",
    "docs/authentication.md",
    "docs/install.md",
    "docs/agent-roster.md",
    "skills/mergecraft/SKILL.md",
    "commands/mergecraft-setup.md",
    "integrations/opencode/commands/mergecraft/setup.md",
)
_AUTH = re.compile(r"mergecraft provider auth ([a-z0-9-]+)\b")
_SCOPE = re.compile(r"mergecraft provider auth [a-z0-9-]+ --scope ([a-z]+)")
_SCOPES = {"local", "github", "both"}


def _text(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def test_init_seeds_every_documented_provider_label(tmp_path: Path) -> None:
    from mergecraft.cli.init_cmd import _config_template
    from mergecraft.cli.provider_cmd import seed_builtin_providers

    config_path = tmp_path / ".mergecraft" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(_config_template(), encoding="utf-8")
    seed_builtin_providers(config_path)

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    RepoSettings.model_validate(raw)
    seeded = {str(row["label"]) for row in raw["providers"]}
    assert set(PROVIDERS) <= seeded, set(PROVIDERS) - seeded
    for relative in _DOCS:
        for label in _AUTH.findall(_text(relative)):
            assert label in seeded, (
                f"{relative} documents `provider auth {label}`, but `init` seeds {sorted(seeded)}"
            )


def test_every_documented_scope_is_accepted_by_the_cli() -> None:
    for relative in _DOCS:
        for scope in _SCOPE.findall(_text(relative)):
            assert scope in _SCOPES, f"{relative} documents --scope {scope}"


def test_the_readme_authenticates_opencode_first() -> None:
    text = _text("README.md")
    block = text.split("**Authenticate** a provider", 1)[1].split("```", 2)[1]
    labels = _AUTH.findall(block)
    assert labels, "the README's authenticate block has no provider example"
    assert labels[0] == "opencode", labels


def test_the_readme_lists_the_major_providers() -> None:
    text = _text("README.md")
    for label in ("opencode", "opencode-go", "openai", "anthropic", "google"):
        assert f"provider auth {label}" in text, label
