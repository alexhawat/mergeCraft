"""Contracts for ``mergecraft provider enable|disable`` (#520).

The disable half is the missing inverse of ``provider auth`` / ``auth
<provider>``: before it, turning a provider off for GitHub CI meant a raw ``gh
secret delete``. These tests pin the contract the issue asks for and the
invariants borrowed from the ``tracing logfire disable`` precedent:

- ``--scope local|github|both`` is honoured, and the scope that is *not*
  selected is genuinely untouched.
- an already-absent Actions secret is success, not an error.
- both credential shapes are cleared: the flat workflow-facing name
  (``NOUS_API_KEY``) and the indexed registry key (``LLM_PROVIDER_<N>_API_KEY``).
- ``auth`` subcommand aliases (``codex``, ``claude``, ``gemini``) resolve onto
  their registry labels.
- disable clears credentials but never the registration, so ``enable`` can
  re-authenticate the same env index.
- no credential *value* is ever printed.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest
from tests.cli.support_provider_registry import (
    read_config,
    read_env_file,
    scaffold_mergecraft_home,
    write_provider_entry,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

TOGGLE_MODULE = "mergecraft.cli.provider_toggle"


def _toggle() -> Any:
    try:
        return importlib.import_module(TOGGLE_MODULE)
    except ImportError as exc:  # pragma: no cover - import guard
        pytest.fail(f"{TOGGLE_MODULE} is not importable: {exc}")


def _capture_secret_delete(monkeypatch: MonkeyPatch, *, ok: bool = True) -> list[str]:
    """Record ``_delete_gh_secret`` calls without shelling out to ``gh``."""
    deleted: list[str] = []

    def _recorder(*, name: str, repo_slug: str) -> bool:
        deleted.append(name)
        return ok

    # ``provider_toggle`` imports the helper inside the function body, so the
    # patch lands on the defining module where that late lookup resolves.
    monkeypatch.setattr("mergecraft.cli.tracing_logfire_cmd._delete_gh_secret", _recorder)
    monkeypatch.setattr(
        "mergecraft.cli.tracing_logfire_cmd._parse_repo_slug",
        lambda: "acme/widgets",
    )
    return deleted


def _seed_repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    monkeypatch.chdir(tmp_path)


def _write_env(tmp_path: Path, pairs: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in pairs.items()]
    (tmp_path / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── secret-name resolution ───────────────────────────────────────────────────


def test_resolve_covers_flat_and_indexed_names_for_a_registered_provider() -> None:
    """A registered provider yields both its flat key and its indexed key."""
    resolved = _toggle().resolve_provider_secrets(
        "nous",
        {"label": "nous", "envIndex": 3, "authKind": "api_key"},
    )

    assert "NOUS_API_KEY" in resolved.github
    assert "LLM_PROVIDER_3_API_KEY" in resolved.github
    assert resolved.label == "nous"


def test_resolve_works_for_an_unregistered_builtin() -> None:
    """A provider authed before the registry existed is still resolvable."""
    resolved = _toggle().resolve_provider_secrets("nous", None)

    assert resolved.github == ("NOUS_API_KEY",)
    assert bool(resolved) is True


def test_resolve_returns_empty_for_an_unknown_label() -> None:
    """An unknown, unregistered label resolves to nothing (the command bails)."""
    assert bool(_toggle().resolve_provider_secrets("not-a-provider", None)) is False


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("codex", "openai"), ("claude", "anthropic"), ("gemini", "google")],
)
def test_auth_subcommand_aliases_resolve_to_registry_labels(alias: str, canonical: str) -> None:
    """``provider disable codex`` and ``... openai`` mean the same provider."""
    assert _toggle().canonical_provider_label(alias) == canonical


def test_codex_alias_clears_both_openai_credential_shapes() -> None:
    """``openai`` carries a subscription blob *and* an API key; both must go."""
    resolved = _toggle().resolve_provider_secrets("codex", None)

    assert set(resolved.github) == {"CODEX_AUTH_JSON", "OPENAI_API_KEY"}


def test_cloud_chain_provider_resolves_its_whole_credential_set() -> None:
    """Bedrock's credentials are a set — clearing one of three leaves CI working."""
    resolved = _toggle().resolve_provider_secrets(
        "bedrock",
        {"label": "bedrock", "envIndex": 8, "authKind": "cloud_chain"},
    )

    assert "AWS_ACCESS_KEY_ID" in resolved.github
    assert "AWS_SECRET_ACCESS_KEY" in resolved.github


# ── disable: github scope ────────────────────────────────────────────────────


def test_disable_github_deletes_the_actions_secret(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The headline case from #520: turn Nous off for CI without touching YAML."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    deleted = _capture_secret_delete(monkeypatch)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "NOUS_API_KEY" in deleted
    assert "LLM_PROVIDER_3_API_KEY" in deleted


def test_disable_github_leaves_the_local_env_untouched(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope github`` must not clear a working local credential."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"NOUS_API_KEY": "local-key"})
    before = (tmp_path / ".env").read_text(encoding="utf-8")
    _capture_secret_delete(monkeypatch)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (tmp_path / ".env").read_text(encoding="utf-8") == before


def test_disable_treats_an_absent_secret_as_success(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The post-condition is "the secret is absent" — already true is still success."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    # ``_delete_gh_secret`` already returns True for a missing secret.
    _capture_secret_delete(monkeypatch, ok=True)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr


def test_disable_bails_when_every_secret_delete_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An unreachable ``gh`` must not report a provider as disabled."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _capture_secret_delete(monkeypatch, ok=False)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "nothing was cleared" in (result.stdout + result.stderr)


# ── disable: local scope ─────────────────────────────────────────────────────


def test_disable_local_blanks_the_env_entries(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Local disable blanks the keys in place rather than deleting the lines."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(
        tmp_path,
        {"NOUS_API_KEY": "local-key", "LLM_PROVIDER_3_API_KEY": "indexed-key"},
    )
    monkeypatch.setattr(
        "mergecraft.cli.tracing_logfire_cmd._parse_repo_slug",
        lambda: pytest.fail("must not resolve a repo under --scope local"),
    )

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "local", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    env = read_env_file(tmp_path)
    assert env["NOUS_API_KEY"] == ""
    assert env["LLM_PROVIDER_3_API_KEY"] == ""


def test_disable_local_never_prints_the_credential_value(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Disable output names keys, never values."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"NOUS_API_KEY": "sk-super-secret-value"})

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "local", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "sk-super-secret-value" not in (result.stdout + result.stderr)


def test_disable_both_clears_local_and_github(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``--scope both`` is the union, not either half."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"NOUS_API_KEY": "local-key"})
    deleted = _capture_secret_delete(monkeypatch)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "both", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "NOUS_API_KEY" in deleted
    assert read_env_file(tmp_path)["NOUS_API_KEY"] == ""


# ── disable: what it must NOT do ─────────────────────────────────────────────


def test_disable_preserves_the_registry_entry(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Disable removes credentials, not registration — ``provider delete`` does that."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _capture_secret_delete(monkeypatch)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    labels = [entry["label"] for entry in read_config(tmp_path).get("providers", [])]
    assert "nous" in labels


def test_disable_preserves_the_env_index_label(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The ``LLM_PROVIDER_<N>`` label is structure, not a credential — it stays."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"LLM_PROVIDER_3": "nous", "LLM_PROVIDER_3_API_KEY": "key"})

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "local", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert read_env_file(tmp_path)["LLM_PROVIDER_3"] == "nous"


def test_disable_rejects_an_unknown_label(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """An unknown label is a usage error, not a silent success."""
    _seed_repo(tmp_path, monkeypatch)

    result = runner.invoke(app, ["provider", "disable", "no-such-provider", "--cwd", str(tmp_path)])

    assert result.exit_code != 0
    assert "unknown provider label" in (result.stdout + result.stderr)


def test_disable_redirects_logfire_to_its_own_toggle(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Logfire is telemetry; ``provider auth`` already rejects it and so must this."""
    _seed_repo(tmp_path, monkeypatch)

    result = runner.invoke(app, ["provider", "disable", "logfire", "--cwd", str(tmp_path)])

    assert result.exit_code != 0
    # Rich wraps the console line, so collapse whitespace before matching.
    collapsed = " ".join((result.stdout + result.stderr).split())
    assert "tracing logfire disable" in collapsed


# ── enable ───────────────────────────────────────────────────────────────────


def test_enable_delegates_to_the_existing_auth_flow(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``enable`` introduces no new credential-minting path (#520 requirement 1)."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    calls: list[tuple[str, str]] = []

    def _fake_auth(entry: dict[str, Any], scope: str, **_kwargs: Any) -> None:
        calls.append((str(entry["label"]), scope))

    monkeypatch.setattr("mergecraft.cli.provider_cmd.run_provider_auth", _fake_auth)

    result = runner.invoke(
        app, ["provider", "enable", "nous", "--scope", "local", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == [("nous", "local")]


def test_enable_rejects_an_unregistered_label(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Enable needs a registry row — it points the operator at ``provider add``."""
    _seed_repo(tmp_path, monkeypatch)

    result = runner.invoke(app, ["provider", "enable", "nous", "--cwd", str(tmp_path)])

    assert result.exit_code != 0
    assert "provider add" in (result.stdout + result.stderr)


# ── round trip ───────────────────────────────────────────────────────────────


def test_disable_then_enable_reuses_the_same_env_index(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The point of preserving registration: re-enabling does not renumber."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"LLM_PROVIDER_3_API_KEY": "key"})
    seen: list[int] = []

    def _fake_auth(entry: dict[str, Any], _scope: str, **_kwargs: Any) -> None:
        seen.append(int(entry["envIndex"]))

    runner.invoke(app, ["provider", "disable", "nous", "--scope", "local", "--cwd", str(tmp_path)])
    monkeypatch.setattr("mergecraft.cli.provider_cmd.run_provider_auth", _fake_auth)
    result = runner.invoke(
        app, ["provider", "enable", "nous", "--scope", "local", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert seen == [3]
