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


def _capture_secret_delete(
    monkeypatch: MonkeyPatch,
    *,
    ok: bool = True,
    fail_names: frozenset[str] = frozenset(),
    slug: str = "acme/widgets",
) -> list[tuple[str, str]]:
    """Record ``_delete_gh_secret`` calls without shelling out to ``gh``.

    Returns ``(secret_name, repo_slug)`` pairs so a test can assert *which*
    repository was targeted, not merely that a delete happened. *fail_names*
    makes individual keys fail, for mixed-outcome cases.
    """
    deleted: list[tuple[str, str]] = []

    def _recorder(*, name: str, repo_slug: str) -> bool:
        deleted.append((name, repo_slug))
        return False if name in fail_names else ok

    # ``provider_toggle`` imports the helper inside the function body, so the
    # patch lands on the defining module where that late lookup resolves.
    monkeypatch.setattr("mergecraft.cli.tracing_logfire_cmd._delete_gh_secret", _recorder)
    # The slug resolver is ``provider_toggle``'s own, and is cwd-anchored; stub
    # it so tests need no real git remote.
    monkeypatch.setattr(
        "mergecraft.cli.provider_toggle.resolve_repo_slug",
        lambda _cwd: slug,
    )
    return deleted


def _deleted_names(calls: list[tuple[str, str]]) -> list[str]:
    return [name for name, _slug in calls]


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
    assert "NOUS_API_KEY" in _deleted_names(deleted)
    assert "LLM_PROVIDER_3_API_KEY" in _deleted_names(deleted)


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
    collapsed = " ".join((result.stdout + result.stderr).split())
    assert "is NOT disabled" in collapsed


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
        "mergecraft.cli.provider_toggle.resolve_repo_slug",
        lambda _cwd: pytest.fail("must not resolve a repo under --scope local"),
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
    assert "NOUS_API_KEY" in _deleted_names(deleted)
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


# ── regressions: destructive targets follow --cwd, not the process cwd ───────


def _init_git_repo(path: Path, *, origin: str) -> None:
    """Create a real git repo at *path* with an ``origin`` remote."""
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", origin],
    ):
        subprocess.run(argv, cwd=path, check=True, capture_output=True)


def test_local_disable_targets_the_cwd_repo_not_the_process_cwd(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--cwd`` selects the registry, so it must select the ``.env`` too.

    Regression: resolving the local target from the *process* working directory
    read the registry from one repository and blanked the ``.env`` of another —
    reporting a provider disabled in a repo the command never touched.
    """
    target = tmp_path / "target-repo"
    current = tmp_path / "current-repo"
    _init_git_repo(target, origin="git@github.com:acme/target.git")
    _init_git_repo(current, origin="git@github.com:acme/current.git")
    scaffold_mergecraft_home(target)
    write_provider_entry(target, label="nous", env_index=3)
    (target / ".env").write_text("NOUS_API_KEY=target-key\n", encoding="utf-8")
    (current / ".env").write_text("NOUS_API_KEY=current-key\n", encoding="utf-8")

    # MERGECRAFT_ENV must be unset, or it would name the target unambiguously
    # and the bug under test could not appear.
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(current)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "local", "--cwd", str(target)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert read_env_file(target)["NOUS_API_KEY"] == ""
    # The repository the operator merely happened to stand in is untouched.
    assert read_env_file(current)["NOUS_API_KEY"] == "current-key"


def test_github_disable_targets_the_cwd_repos_origin(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The Actions secrets deleted must belong to the ``--cwd`` repository."""
    target = tmp_path / "target-repo"
    current = tmp_path / "current-repo"
    _init_git_repo(target, origin="git@github.com:acme/target.git")
    _init_git_repo(current, origin="git@github.com:acme/current.git")
    scaffold_mergecraft_home(target)
    write_provider_entry(target, label="nous", env_index=3)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.chdir(current)

    deleted: list[tuple[str, str]] = []

    def _recorder(*, name: str, repo_slug: str) -> bool:
        deleted.append((name, repo_slug))
        return True

    # Note: ``resolve_repo_slug`` is deliberately NOT stubbed here — the whole
    # point is that it reads the remote of the ``--cwd`` repository.
    monkeypatch.setattr("mergecraft.cli.tracing_logfire_cmd._delete_gh_secret", _recorder)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "github", "--cwd", str(target)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert deleted, "no secret delete was attempted"
    assert {slug for _name, slug in deleted} == {"acme/target"}


def test_resolve_repo_slug_reads_the_requested_repository(tmp_path: Path) -> None:
    """Unit-level: the slug comes from *cwd*'s origin remote."""
    repo = tmp_path / "somewhere"
    _init_git_repo(repo, origin="https://github.com/acme/widgets.git")

    assert _toggle().resolve_repo_slug(repo) == "acme/widgets"


# ── regressions: partial failure is not "disabled" ───────────────────────────


def test_partial_secret_delete_failure_is_not_reported_as_disabled(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A surviving credential means the provider is not disabled.

    Regression: ``openai`` carries both ``CODEX_AUTH_JSON`` and
    ``OPENAI_API_KEY``. An absent ``CODEX_AUTH_JSON`` counts as deleted, which
    was enough to print "disabled" while a live ``OPENAI_API_KEY`` survived a
    failed deletion — the provider stayed fully usable in CI.
    """
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="openai", env_index=1, auth_kind="device_code")
    _capture_secret_delete(monkeypatch, fail_names=frozenset({"OPENAI_API_KEY"}))

    result = runner.invoke(
        app, ["provider", "disable", "openai", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code != 0
    collapsed = " ".join((result.stdout + result.stderr).split())
    assert "is NOT disabled" in collapsed
    assert "OPENAI_API_KEY" in collapsed
    assert "disabled." not in collapsed.replace("is NOT disabled", "")


def test_mixed_scope_failure_bails_even_when_the_other_half_succeeded(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope both`` with a good local write and a failed delete still bails."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"NOUS_API_KEY": "local-key"})
    _capture_secret_delete(monkeypatch, ok=False)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "both", "--cwd", str(tmp_path)]
    )

    assert result.exit_code != 0
    # The local half still happened — the command is not transactional, and the
    # error names what is left rather than pretending nothing was cleared.
    assert read_env_file(tmp_path)["NOUS_API_KEY"] == ""


def test_local_partial_failure_bails(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """One unwritable ``.env`` key is enough to withhold the disabled claim."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="nous", env_index=3)
    _write_env(tmp_path, {"NOUS_API_KEY": "k", "LLM_PROVIDER_3_API_KEY": "k"})

    real_write = importlib.import_module("mergecraft.cli.auth_cmd")._write_env_value

    def _flaky(env_path: Path, key: str, value: str) -> bool:
        if key == "LLM_PROVIDER_3_API_KEY":
            return False
        return bool(real_write(env_path, key, value))

    monkeypatch.setattr("mergecraft.cli.auth_cmd._write_env_value", _flaky)

    result = runner.invoke(
        app, ["provider", "disable", "nous", "--scope", "local", "--cwd", str(tmp_path)]
    )

    assert result.exit_code != 0
    collapsed = " ".join((result.stdout + result.stderr).split())
    assert "LLM_PROVIDER_3_API_KEY" in collapsed


def test_all_keys_cleared_still_reports_disabled(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The tightened check must not withhold success from the happy path."""
    _seed_repo(tmp_path, monkeypatch)
    write_provider_entry(tmp_path, label="openai", env_index=1, auth_kind="device_code")
    _capture_secret_delete(monkeypatch)

    result = runner.invoke(
        app, ["provider", "disable", "openai", "--scope", "github", "--cwd", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "disabled" in " ".join((result.stdout + result.stderr).split())


# ── regression: Google's documented API-key alias ────────────────────────────


def test_google_clears_its_documented_api_key_alias() -> None:
    """``GOOGLE_GENERATIVE_AI_API_KEY`` authenticates Google just as well.

    Regression: clearing only ``GEMINI_API_KEY`` reported the provider disabled
    while the alias kept it authenticated. ``models.py`` lists both as Google's
    ``env_vars`` and ``docs/authentication.md`` documents the alias.
    """
    resolved = _toggle().resolve_provider_secrets("google", None)

    assert set(resolved.github) == {"GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"}


def test_google_alias_matches_the_provider_catalog() -> None:
    """The disable map must not drift from ``models.PROVIDERS``' ``env_vars``."""
    from mergecraft.models import PROVIDERS

    catalog = set(PROVIDERS["google"].env_vars)
    resolved = set(_toggle().resolve_provider_secrets("google", None).github)

    assert catalog <= resolved, (
        f"credentials in the catalog but never cleared: {catalog - resolved}"
    )
