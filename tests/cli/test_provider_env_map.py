"""Provider commands must read ``.env`` the way the startup load does.

``provider status`` reads the local ``.env`` through
``provider_cmd._read_env_map``, while the CLI startup load (and ``auth``) write
and export the same file through ``python-dotenv``. Today the two disagree:
``_read_env_map`` strips double quotes only, so single-quoted values (the shape
``auth_cmd._write_env_value`` writes for anything not shell-word-safe),
``export `` prefixes, inline comments and ``${VAR}`` interpolation all mean
something different to each reader.

The contract is one file with one meaning: ``_read_env_map`` returns exactly
what the startup load exports. The expected maps here are frozen literals
produced by running the current ``python-dotenv`` reader over the same corpus —
the ladder both readers share by construction.

Importing ``mergecraft.config.env`` and reading its ``LocalDotEnv`` is what the
implementation adds; the assertions below are red until that lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

# ``export ``, an empty value, a bare key, double/single quotes, a comment, an
# inline comment, interpolation and a quoted hash all in one file.
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

# Frozen literal — ``DotEnv(interpolate=True, override=False).dict()`` for
# ``_CORPUS`` (the same ladder ``load_dotenv(override=False)`` exports).
_CORPUS_EXPECTED = {
    "A": "1",
    "B": "",
    "D": "x y",
    "E": "q",
    "F": "1z",
    "G": "inline",
    "H": "hash # inside",
}

# The three quote shapes ``auth_cmd._write_env_value`` produces: a bare
# shell-word-safe value, a spaced value, and a single-quoted JSON blob with
# escaped newlines.
_WRITE_VALUES = {
    "WORDSAFE": "tk_simple-token_123",
    "WITHSPACE": "hello world",
    "JSONISH": '{"type":"service_account","private_key":"line1\\nline2"}',
}


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_read_env_map_matches_the_startup_load_on_the_corpus(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every quote mode, ``export``, inline comment and interpolation mean the same."""
    from mergecraft.cli.provider_cmd import _read_env_map

    env_path = tmp_path / "corpus.env"
    _write(env_path, _CORPUS)

    # ``F=${A}z`` interpolates from the *process* environment (python-dotenv
    # resolves with ``os.environ`` winning over the file's own values for an
    # ``override=False`` read), so the frozen literal only holds in a clean
    # environment. Clear the corpus keys for the duration of the read instead of
    # inheriting whatever a previous test left behind.
    for key in _CORPUS_KEYS:
        monkeypatch.delenv(key, raising=False)

    assert _read_env_map(env_path) == _CORPUS_EXPECTED


def test_read_env_map_round_trips_write_env_value_quoting(tmp_path: Path) -> None:
    """A value written by ``auth`` reads back verbatim, however it was quoted."""
    from mergecraft.cli.auth_cmd import _write_env_value
    from mergecraft.cli.provider_cmd import _read_env_map

    env_path = tmp_path / ".env"
    for key, value in _WRITE_VALUES.items():
        assert _write_env_value(env_path, key, value) is True

    assert _read_env_map(env_path) == _WRITE_VALUES


def test_read_env_map_round_trips_a_single_quoted_multiline_json_blob(tmp_path: Path) -> None:
    """The credential shape ``auth provider`` writes survives the read intact."""
    from mergecraft.cli.auth_cmd import _write_env_value
    from mergecraft.cli.provider_cmd import _read_env_map

    env_path = tmp_path / ".env"
    payload = '{\n  "type": "service_account",\n  "project_id": "demo"\n}'
    assert _write_env_value(env_path, "SERVICE_ACCOUNT", payload) is True

    assert _read_env_map(env_path) == {"SERVICE_ACCOUNT": payload}


def test_read_env_map_ignores_a_missing_file(tmp_path: Path) -> None:
    """A repo with no ``.env`` reads as an empty map, silently."""
    from mergecraft.cli.provider_cmd import _read_env_map

    assert _read_env_map(tmp_path / "absent.env") == {}


def test_read_env_map_keeps_a_key_whose_value_is_empty(tmp_path: Path) -> None:
    """``B=`` is a present key with an empty value, not a dropped line."""
    from mergecraft.cli.provider_cmd import _read_env_map

    env_path = tmp_path / ".env"
    _write(env_path, "B=\n")

    assert _read_env_map(env_path) == {"B": ""}
