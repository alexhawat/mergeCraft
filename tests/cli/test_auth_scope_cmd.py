"""RED contracts for ``mergecraft auth <provider> --scope`` (issue #221 / D11).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-19-wave-plan.md``
Batch F / W23 — test-creator. Issue #221: every ``mergecraft auth <provider>``
command except ``logfire`` persists the captured credential **only** through
``gh secret set``, so a contributor who authenticates cannot then run the CLI
locally — the credential exists in GitHub Actions secrets and nowhere else.

D11 (plan line 183) scopes the fix to the seven provider commands that capture
a credential the local runtime reads out of ``os.environ``: ``codex``,
``claude``, ``gemini``, ``cursor``, ``nous``, ``tokenhub``, ``minimax``.
``logfire`` is excluded — it is the reference implementation this suite copies
(``cli/auth_cmd.py:583-733``) and its default is ``both``, not ``github``.

What is pinned here:

- ``--scope local`` writes the credential into ``.env`` and **succeeds without
  a working ``gh``**: neither ``_get_gh_token`` nor ``_parse_git_remote`` nor
  ``_set_gh_secret`` may be reached, and the command still exits 0.
- The local write is asserted by **reading the value back** with
  ``dotenv_values`` under the key the runtime resolves (``CODEX_AUTH_JSON``,
  ``NOUS_API_KEY``, …). A write that lands an empty or unparseable value fails.
- **default (no flag) and ``--scope github``** are today's behaviour exactly —
  one ``gh secret set``, no ``.env`` touched. The no-flag arms are **green
  today** and must stay green: they are the #221 compatibility guard.
- ``--scope both`` does both, and a failed ``gh secret set`` with a successful
  local write is **partial success** (exit 0 + warning) — the contract
  ``auth logfire`` already implements at ``cli/auth_cmd.py:717-734``.
- ``auth codex`` captures its credential inside an isolated ``CODEX_HOME``
  tempdir that is then deleted (``cli/auth_cmd.py:123-138``). The local write
  must carry the captured bytes, not the empty string a post-cleanup re-read
  would produce — pinned by exact round-trip equality against the payload the
  faked ``codex login`` wrote.
- An invalid ``--scope`` value is rejected by ``_normalise_scope``'s existing
  contract: ``typer.Exit(1)`` plus a message naming the three valid values.

No test in this file touches a real ``.env``, a real credential, ``gh``,
``git``, ``codex``, or the network. ``MERGECRAFT_ENV`` pins every ``.env``
write to ``tmp_path``; every provider validator is stubbed.
"""

from __future__ import annotations

import getpass
import importlib
import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from dotenv import dotenv_values
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

XFAIL_REASON = "green after W24: auth --scope local/github/both"

# D11's provider set → the env key the local runtime reads for that provider.
PROVIDERS: list[tuple[str, str]] = [
    ("codex", "CODEX_AUTH_JSON"),
    ("claude", "CLAUDE_CODE_OAUTH_TOKEN"),
    ("gemini", "GEMINI_API_KEY"),
    ("cursor", "CURSOR_API_KEY"),
    ("nous", "NOUS_API_KEY"),
    ("tokenhub", "TOKENHUB_API_KEY"),
    ("minimax", "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"),
]

# Single-line JSON so the payload survives a ``.env`` round trip regardless of
# the quote mode W24 picks. Multi-line ``auth.json`` handling is deliberately
# left unpinned — see the test-plan doc's "left to W24" section.
CODEX_AUTH_PAYLOAD = (
    '{"tokens": {"access_token": "codex-red-access", "refresh_token": "codex-red-refresh"}, '
    '"last_refresh": "2026-08-19T00:00:00Z"}'
)
# ``sk-ant-oat`` prefix so ``auth claude`` takes the no-warning branch.
CLAUDE_TOKEN = "sk-ant-oat-scope-red-token"

CREDENTIALS: dict[str, str] = {
    "codex": CODEX_AUTH_PAYLOAD,
    "claude": CLAUDE_TOKEN,
    "gemini": "gemini-scope-red-key",
    "cursor": "cursor-scope-red-key",
    "nous": "nous-scope-red-key",
    "tokenhub": "tokenhub-scope-red-key",
    "minimax": "minimax-scope-red-key",
}

PRESERVED_KEY = "MERGECRAFT_SCOPE_RED_PRESERVED"
PRESERVED_VALUE = "keep-me"


def _load_auth_cmd() -> Any:
    """Lazy import so a missing symbol fails with a clear message, not at collection."""
    try:
        return importlib.import_module("mergecraft.cli.auth_cmd")
    except ImportError as exc:
        pytest.fail(f"mergecraft.cli.auth_cmd not importable: {exc}")


def _stub_validators(module: Any, monkeypatch: MonkeyPatch) -> None:
    """Make every ``_validate_*`` helper accept, so no test reaches the network."""
    for name in dir(module):
        if name.startswith("_validate_"):
            monkeypatch.setattr(module, name, lambda *_a, **_kw: True)


class GhRecorder:
    """Records the gh-facing helper calls a subcommand makes."""

    def __init__(self) -> None:
        self.token_calls = 0
        self.remote_calls = 0
        self.secrets: list[dict[str, str]] = []
        self.secret_result = True

    def install(self, module: Any, monkeypatch: MonkeyPatch) -> None:
        """Replace ``_get_gh_token`` / ``_parse_git_remote`` / ``_set_gh_secret``."""

        def _token() -> str:
            self.token_calls += 1
            return "gh-token"

        def _remote() -> tuple[str, str]:
            self.remote_calls += 1
            return "acme", "widgets"

        def _secret(*, name: str, value: str, repo_slug: str) -> bool:
            self.secrets.append({"name": name, "value": value, "repo_slug": repo_slug})
            return self.secret_result

        monkeypatch.setattr(module, "_get_gh_token", _token)
        monkeypatch.setattr(module, "_parse_git_remote", _remote)
        monkeypatch.setattr(module, "_set_gh_secret", _secret)

    @property
    def touched_gh(self) -> bool:
        """True when any gh-facing helper ran."""
        return bool(self.token_calls or self.remote_calls or self.secrets)


class CodexLoginStub:
    """Fakes ``codex login --device-auth`` writing ``auth.json`` into ``CODEX_HOME``."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.homes: list[Path] = []

    def install(self, module: Any, monkeypatch: MonkeyPatch) -> None:
        """Stub the PATH probe and the ``subprocess.run`` that mints the credential."""
        from pathlib import Path as _Path

        monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/codex")

        def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            env = kwargs.get("env") or {}
            home = _Path(env["CODEX_HOME"])
            self.homes.append(home)
            (home / "auth.json").write_text(self.payload, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(module.subprocess, "run", _run)


def _arrange_provider(
    provider: str, module: Any, monkeypatch: MonkeyPatch
) -> tuple[str, CodexLoginStub | None]:
    """Wire the credential-capture side of one provider; return its value."""
    value = CREDENTIALS[provider]
    _stub_validators(module, monkeypatch)
    if provider == "codex":
        stub = CodexLoginStub(value)
        stub.install(module, monkeypatch)
        return value, stub
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: value)
    return value, None


def _pin_env_path(tmp_path: Path, monkeypatch: MonkeyPatch, *, precreate: bool) -> Path:
    """Point ``_local_env_path`` at a temp file so no real ``.env`` is touched."""
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    if precreate:
        env_path.write_text(f"{PRESERVED_KEY}={PRESERVED_VALUE}\n", encoding="utf-8")
    return env_path


def _read_back(env_path: Path, key: str) -> str | None:
    """Return the value a local run would resolve for ``key`` from ``env_path``."""
    return dotenv_values(str(env_path)).get(key)


def _flat(result: Any) -> str:
    """Collapse CLI output to a single whitespace-normalised lower-case line."""
    return " ".join((result.stdout + result.stderr).split()).lower()


# ── --scope local: writes .env, needs no working gh ──────────────────────────


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
@pytest.mark.parametrize(("provider", "env_key"), PROVIDERS)
def test_auth_scope_local_writes_env_without_gh(
    provider: str, env_key: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope local`` lands a readable credential in ``.env`` and never touches gh.

    This is the whole of #221: a contributor with no ``gh`` auth and no network
    must still end up with a credential the local CLI can read. The assertion
    is a *round trip* — ``dotenv_values`` resolves the key to the captured
    value — so an attempted-but-empty write cannot pass.
    """
    module = _load_auth_cmd()
    value, _ = _arrange_provider(provider, module, monkeypatch)
    gh = GhRecorder()
    gh.secret_result = False  # a machine with no gh auth
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=True)

    result = runner.invoke(app, ["auth", provider, "--scope", "local"])

    assert result.exit_code == 0, _flat(result)
    assert not gh.touched_gh, (
        f"--scope local must not reach gh; token={gh.token_calls} "
        f"remote={gh.remote_calls} secrets={gh.secrets}"
    )
    assert _read_back(env_path, env_key) == value
    assert _read_back(env_path, PRESERVED_KEY) == PRESERVED_VALUE


# ── --scope github: today's behaviour, .env untouched ───────────────────────


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
@pytest.mark.parametrize(("provider", "env_key"), PROVIDERS)
def test_auth_scope_github_writes_secret_only(
    provider: str, env_key: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Explicit ``--scope github`` sets the Actions secret and writes no ``.env``."""
    module = _load_auth_cmd()
    value, _ = _arrange_provider(provider, module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", provider, "--scope", "github"])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == [env_key]
    assert gh.secrets[0]["value"] == value
    assert gh.secrets[0]["repo_slug"] == "acme/widgets"
    assert not env_path.exists(), f"--scope github must not create {env_path}"


# ── --scope both: both layers ───────────────────────────────────────────────


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
@pytest.mark.parametrize(("provider", "env_key"), PROVIDERS)
def test_auth_scope_both_writes_env_and_secret(
    provider: str, env_key: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope both`` writes the local ``.env`` **and** sets the Actions secret."""
    module = _load_auth_cmd()
    value, _ = _arrange_provider(provider, module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=True)

    result = runner.invoke(app, ["auth", provider, "--scope", "both"])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == [env_key]
    assert gh.secrets[0]["value"] == value
    assert _read_back(env_path, env_key) == value


# ── compatibility guard: no flag == today's github-only behaviour (green) ────


@pytest.mark.parametrize(("provider", "env_key"), PROVIDERS)
def test_auth_default_scope_is_github_only(
    provider: str, env_key: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No ``--scope`` flag → exactly today's behaviour: one secret, no ``.env``.

    Green **before and after** W24 by construction (D11 keeps ``github`` the
    default). This is the #221 compatibility guard: if W24 flips the default to
    ``local`` or ``both``, every existing operator's flow changes silently and
    these seven arms are what says so.
    """
    module = _load_auth_cmd()
    value, _ = _arrange_provider(provider, module, monkeypatch)
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", provider])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == [env_key]
    assert gh.secrets[0]["value"] == value
    assert not env_path.exists(), (
        f"the default scope must stay github-only; {env_path} was written with "
        f"{env_path.read_text(encoding='utf-8') if env_path.exists() else '<absent>'}"
    )


# ── invalid --scope: _normalise_scope's existing contract ───────────────────


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
@pytest.mark.parametrize(("provider", "env_key"), PROVIDERS)
def test_auth_rejects_unknown_scope(
    provider: str, env_key: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An unknown ``--scope`` bails ``Exit(1)`` naming the three valid values.

    Matched to ``_normalise_scope`` as it already behaves for ``auth logfire``
    (``cli/auth_cmd.py:583-598``) rather than invented: exit code 1 (a
    ``_bail``, not Typer's usage exit 2) and a message that lists ``local``,
    ``github`` and ``both``. Nothing is captured or written first.
    """
    module = _load_auth_cmd()
    _arrange_provider(provider, module, monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "must-not-prompt")
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", provider, "--scope", "everywhere"])

    assert result.exit_code == 1, (
        f"expected a _bail (exit 1), got {result.exit_code}: {_flat(result)}"
    )
    output = _flat(result)
    assert "expected one of" in output, output
    for valid in ("local", "github", "both"):
        assert valid in output, output
    assert gh.secrets == []
    assert not env_path.exists()


# ── the tempdir-ordering half of #221 (auth codex only) ─────────────────────


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
def test_auth_codex_scope_local_persists_the_captured_auth_json(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The local write carries the ``auth.json`` bytes, not a post-cleanup empty read.

    ``auth codex`` mints its credential inside a ``tempfile.TemporaryDirectory``
    used as ``CODEX_HOME`` and lets it be deleted on block exit
    (``cli/auth_cmd.py:123-138``). A local-scope write bolted on *after* that
    teardown would re-read a path that no longer exists and persist nothing —
    and a test that only asserts "``_dotenv_set_key`` was called" would pass.

    So the assertion is on the **content**: the value handed to
    ``_dotenv_set_key`` is the exact payload the faked login wrote, it is
    non-empty, it parses back as the same JSON object, and it survives a
    ``dotenv_values`` round trip. Ordering itself is deliberately *not*
    asserted — an implementation that keeps the value in scope and writes after
    teardown is correct, and pinning call order would reject it.
    """
    module = _load_auth_cmd()
    value, codex = _arrange_provider("codex", module, monkeypatch)
    assert codex is not None
    gh = GhRecorder()
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    real_set_key = module._dotenv_set_key
    written: list[tuple[str, str]] = []

    def _spy(path: str, key: str, val: str, **kwargs: Any) -> Any:
        written.append((key, val))
        return real_set_key(path, key, val, **kwargs)

    monkeypatch.setattr(module, "_dotenv_set_key", _spy)

    result = runner.invoke(app, ["auth", "codex", "--scope", "local"])

    assert result.exit_code == 0, _flat(result)
    assert codex.homes, "the faked codex login never ran"
    assert not codex.homes[0].exists(), "the isolated CODEX_HOME must still be cleaned up"

    codex_writes = [val for key, val in written if key == "CODEX_AUTH_JSON"]
    assert codex_writes, f"CODEX_AUTH_JSON was never written; saw {[k for k, _ in written]}"
    assert codex_writes[-1] == value, (
        "the persisted CODEX_AUTH_JSON must be the captured auth.json verbatim; "
        f"got {codex_writes[-1]!r}"
    )
    assert json.loads(codex_writes[-1])["tokens"]["access_token"] == "codex-red-access"
    assert _read_back(env_path, "CODEX_AUTH_JSON") == value


# ── partial success under --scope both (the logfire contract) ───────────────


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
def test_auth_codex_scope_both_survives_a_failed_gh_secret_set(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A failed ``gh secret set`` with a good local write is partial success.

    Pinned to match ``auth logfire`` (``cli/auth_cmd.py:717-734``): the gh half
    failing prints a warning pointing at the repo settings page and the command
    still exits 0, because the operator did get a usable local credential.
    """
    module = _load_auth_cmd()
    value, _ = _arrange_provider("codex", module, monkeypatch)
    gh = GhRecorder()
    gh.secret_result = False
    gh.install(module, monkeypatch)
    env_path = _pin_env_path(tmp_path, monkeypatch, precreate=False)

    result = runner.invoke(app, ["auth", "codex", "--scope", "both"])

    assert result.exit_code == 0, _flat(result)
    assert [record["name"] for record in gh.secrets] == ["CODEX_AUTH_JSON"]
    assert _read_back(env_path, "CODEX_AUTH_JSON") == value
    output = _flat(result)
    assert "warning" in output or "manually" in output, output


@pytest.mark.xfail(reason=XFAIL_REASON, strict=False)
def test_auth_codex_scope_both_bails_when_neither_half_lands(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Both halves failing is a hard failure, not a silent success.

    The other side of the partial-success contract
    (``cli/auth_cmd.py:730-734``): when the local write *and* the secret write
    both fail, the operator must be told nothing was saved.
    """
    module = _load_auth_cmd()
    _arrange_provider("codex", module, monkeypatch)
    gh = GhRecorder()
    gh.secret_result = False
    gh.install(module, monkeypatch)
    _pin_env_path(tmp_path, monkeypatch, precreate=False)
    monkeypatch.setattr(module, "_write_env_value", lambda *_a, **_kw: False)

    result = runner.invoke(app, ["auth", "codex", "--scope", "both"])

    assert result.exit_code != 0, _flat(result)
    assert "nothing was written" in _flat(result), _flat(result)


# ── structural / collection smoke (green today) ─────────────────────────────


def test_d11_provider_subcommands_are_all_registered() -> None:
    """Every D11 provider command exists on ``mergecraft auth`` today.

    Collection-only guard: W23 pins ``--scope`` onto an existing surface, so if
    a provider name here does not match a real subcommand the reds above would
    be failing for the wrong reason.
    """
    result = runner.invoke(app, ["auth", "--help"])

    assert result.exit_code == 0
    output = result.stdout.lower()
    missing = [provider for provider, _ in PROVIDERS if provider not in output]
    assert not missing, f"auth --help is missing {missing}; got: {result.stdout!r}"
