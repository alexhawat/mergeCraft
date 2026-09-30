"""E5 — the startup ``.env`` load inside GitHub Actions (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

Locked contract **TB-D14**: inside GitHub Actions the startup load reads no
``.env`` unless ``$MERGECRAFT_ENV`` names a file. The predicate is the same one
``config/layered.py`` uses for ``config.local.yaml``
(:func:`mergecraft.config.layered.running_in_github_actions`). Outside Actions
nothing changes; ``.env`` writers (``auth`` / ``provider auth``) are untouched.

A reviewed checkout can add a ``.env`` at the git root, and
``docker-entrypoint.sh`` runs ``mergecraft gha`` from the job workspace — so
without this rule a PR controls the startup environment.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from mergecraft.cli import app as cli_app
from mergecraft.config.layered import running_in_github_actions

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_KEY = "MERGECRAFT_LOGFIRE_TOKEN"


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "deep").mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return root


@pytest.fixture(autouse=True)
def _isolate_ambient_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Stop the walk-up and clear the env keys this module asserts on.

    The default for these tests is the *non-Actions* environment: ``GITHUB_ACTIONS``
    is cleared here, and the Actions cases opt back in with an explicit
    ``monkeypatch.setenv("GITHUB_ACTIONS", ...)``. That keeps each test's
    expectation (inside vs outside Actions) stated at the point of use rather
    than inherited from the runner (TB-D14).
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv(_KEY, raising=False)


def test_actions_does_not_load_a_workspace_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """TB-D14 — a ``.env`` in the checked-out workspace is not read in Actions."""
    root = _git_repo(tmp_path)
    (root / ".env").write_text(f"{_KEY}=from-workspace\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert _KEY not in os.environ


@pytest.mark.parametrize("flag", ["true", "True", "TRUE"])
def test_actions_predicate_is_case_insensitive(
    tmp_path: Path, monkeypatch: MonkeyPatch, flag: str
) -> None:
    """TB-D14 — the predicate matches ``running_in_github_actions`` exactly."""
    root = _git_repo(tmp_path)
    (root / ".env").write_text(f"{_KEY}=from-workspace\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", flag)
    monkeypatch.chdir(root / "src" / "deep")

    assert running_in_github_actions() is True
    cli_app._load_local_env()

    assert _KEY not in os.environ


def test_actions_loads_an_explicit_mergecraft_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Guard — ``$MERGECRAFT_ENV`` names the one file the Action may read."""
    root = _git_repo(tmp_path)
    explicit = tmp_path / "explicit.env"
    explicit.write_text(f"{_KEY}=from-explicit\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("MERGECRAFT_ENV", str(explicit))
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ[_KEY] == "from-explicit"


def test_outside_actions_the_root_env_loads_as_today(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Guard — outside Actions the walk-up to the git root is unchanged."""
    root = _git_repo(tmp_path)
    (root / ".env").write_text(f"{_KEY}=from-root\n", encoding="utf-8")
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ[_KEY] == "from-root"


def test_preset_keys_still_win_over_the_env_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Guard — ``override=False`` is the contract; operator env wins."""
    root = _git_repo(tmp_path)
    (root / ".env").write_text(f"{_KEY}=from-root\n", encoding="utf-8")
    monkeypatch.setenv(_KEY, "preset-by-operator")
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ[_KEY] == "preset-by-operator"


def test_actions_with_no_env_file_is_a_silent_noop(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Guard — a missing file stays silent-on-missing in Actions."""
    root = _git_repo(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert _KEY not in os.environ


# ── the ``.env`` corpus: one parser, one meaning ────────────────────────────

_CORPUS = (
    "export A=1\n"
    "B=\n"
    "bare C\n"
    'D="x y"\n'
    "E='q'\n"
    "# a comment\n"
    "F=${A}z\n"
    "G=inline # comment\n"
    'H="hash # inside"\n'
)
_CORPUS_KEYS = ["A", "B", "C", "D", "E", "F", "G", "H"]
# Frozen literal — ``load_dotenv(override=False, encoding="utf-8")`` over
# ``_CORPUS`` in a clean environment.
_CORPUS_EXPECTED = {
    "A": "1",
    "B": "",
    "C": None,
    "D": "x y",
    "E": "q",
    "F": "1z",
    "G": "inline",
    "H": "hash # inside",
}


def _clear_corpus_keys(monkeypatch: MonkeyPatch) -> None:
    for key in _CORPUS_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_corpus_loads_exactly_like_load_dotenv(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``export``, a bare key, empty values, quotes, comments and interpolation.

    The startup load populates ``os.environ`` with the same map
    ``load_dotenv(override=False)`` produces: the bare ``C`` line is dropped,
    ``B=`` is a present empty value, ``E='q'`` loses its single quotes, the
    inline comment is stripped and ``F`` interpolates ``A``.
    """
    root = _git_repo(tmp_path)
    (root / ".env").write_text(_CORPUS, encoding="utf-8")
    _clear_corpus_keys(monkeypatch)
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    observed = {key: os.environ.get(key) for key in _CORPUS_KEYS}
    assert observed == _CORPUS_EXPECTED


def test_corpus_pre_set_environment_wins(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``override=False`` is the contract: a preset key is not replaced.

    The interpolation of ``F`` still reads the *process* value of ``A`` — the
    same thing ``load_dotenv`` does — so the file and the process agree on one
    meaning.
    """
    root = _git_repo(tmp_path)
    (root / ".env").write_text(_CORPUS, encoding="utf-8")
    _clear_corpus_keys(monkeypatch)
    monkeypatch.setenv("A", "PROCESS")
    monkeypatch.setenv("D", "preset-d")
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ["A"] == "PROCESS"
    assert os.environ["D"] == "preset-d"
    assert os.environ["E"] == "q"
    assert os.environ["F"] == "PROCESSz"


def test_actions_reads_only_the_explicit_env_over_the_workspace_corpus(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """In Actions, ``MERGECRAFT_ENV`` selects one file; the workspace corpus is ignored."""
    root = _git_repo(tmp_path)
    (root / ".env").write_text(_CORPUS, encoding="utf-8")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("A=from-explicit\n", encoding="utf-8")
    _clear_corpus_keys(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("MERGECRAFT_ENV", str(explicit))
    monkeypatch.chdir(root / "src" / "deep")

    cli_app._load_local_env()

    assert os.environ["A"] == "from-explicit"
    assert "D" not in os.environ, "the workspace corpus must not be read in Actions"
