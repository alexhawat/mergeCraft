"""The repo YAML is a plain model: no environment name overrides a repo field.

`RepoSettings` has fields named ``shell``, ``push`` and ``model``. If it were a
`pydantic_settings.BaseSettings`, each of those would read an environment
variable of the same name — and ``SHELL=/bin/bash`` is set in every login shell,
which would fail the shell-permission validation for every local run. The repo
file is also repo-authored and trust-tiered, so it must never gain environment
overrides, and its precedence is a layered merge rather than a source-priority
list.

These assertions are the contract, not a style preference: the frozen table
below is what the code does today, and the ``BaseSettings`` walk fails the
moment a repo-config model starts inheriting the environment. No ``xfail``
marker is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from mergecraft.config import settings as settings_module
from mergecraft.config.layered import resolve_config_sources
from mergecraft.config.settings import RepoSettings, default_settings, load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_POISON = {
    "SHELL": "/bin/bash",
    "PUSH": "enabled",
    "MODEL": "anthropic/claude-opus",
    "STATUS_CHECKS": "enabled",
    "TOKENBUDGET": "123",
    "MAXDIFFLINES": "7",
    "RUNBOUNDS": '{"tokenBudget": 1}',
}


def _settings_models() -> list[type[BaseModel]]:
    """Every Pydantic model the repo-config module defines."""
    return [
        value
        for value in vars(settings_module).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == settings_module.__name__
    ]


def test_repo_settings_is_not_a_base_settings() -> None:
    """The repo YAML is a plain ``BaseModel`` fed by the layered loader."""
    assert not issubclass(RepoSettings, BaseSettings)


def test_no_repo_config_model_reads_the_environment() -> None:
    """No model in the repo-config module is a ``BaseSettings``."""
    offenders = sorted(
        model.__name__ for model in _settings_models() if issubclass(model, BaseSettings)
    )
    assert not offenders, (
        "repo-config models must stay plain BaseModels; a BaseSettings field named "
        f"`shell` would read the login shell: {offenders}"
    )


def test_repo_settings_forbid_unknown_keys() -> None:
    """The repo YAML hard-fails an unknown key (``extra="forbid"``)."""
    assert RepoSettings.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("poison", sorted(_POISON), ids=sorted(_POISON))
def test_a_repo_field_name_in_the_environment_changes_nothing(
    poison: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``SHELL``/``PUSH``/``MODEL`` in the environment never reach the repo settings."""
    for name in _POISON:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.setenv(poison, _POISON[poison])

    loaded = load_repo_settings(root=tmp_path)

    assert loaded.model_dump() == default_settings().model_dump()


def test_the_login_shell_does_not_fail_shell_permission(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A real ``SHELL=/bin/zsh`` must not be validated as the repo's shell policy."""
    for name in _POISON:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHELL", "/bin/zsh")

    loaded = load_repo_settings(root=tmp_path)

    assert loaded.shell == default_settings().shell


def test_a_repo_file_still_decides_the_repo_fields(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """The env poison does not shadow the file: the committed YAML still wins."""
    for name in _POISON:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("PUSH", "disabled")

    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "shell: enabled\npush: enabled\nmodel: anthropic/claude-sonnet\n",
        encoding="utf-8",
    )

    loaded = load_repo_settings(root=tmp_path)

    assert loaded.shell == "enabled"
    assert loaded.push == "enabled"
    assert loaded.model == "anthropic/claude-sonnet"


def test_the_config_locator_still_reads_mergecraft_config_explicitly(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``MERGECRAFT_CONFIG`` is an explicit locator, not a field-name override."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    override = tmp_path / "override.yaml"
    override.write_text("model: anthropic/claude-sonnet\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(override))

    loaded = load_repo_settings(root=tmp_path)
    sources = resolve_config_sources(tmp_path)

    assert loaded.model == "anthropic/claude-sonnet"
    assert [path.name for path in sources.files] == ["override.yaml"]
