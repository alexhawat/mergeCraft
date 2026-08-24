"""RED tests for ``mergecraft provider`` registry CLI (#477 / BA).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BA — test-creator. Pins add/list/edit/delete, harness validation, config/env split,
permanent env indices, and built-in harness defaults (D3-D4).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml
from tests.cli.support_provider_registry import (
    BUILTIN_HARNESS_DEFAULTS,
    CUSTOM_BASE_URL,
    NOUS_BASE_URL,
    import_provider_cmd,
    provider_entries,
    read_config,
    read_env_file,
    scaffold_mergecraft_home,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.models import PROVIDERS

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _require_provider_command() -> None:
    """Fail until ``provider`` is registered on the Typer app."""
    result = _invoke("provider", "--help")
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail("mergecraft provider is not registered yet")


# ---------------------------------------------------------------------------
# CLI surface — verbs exist
# ---------------------------------------------------------------------------


def test_provider_help_lists_registry_verbs() -> None:
    _require_provider_command()
    result = _invoke("provider", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for verb in ("add", "list", "edit", "delete", "harnesses"):
        assert verb in output, f"expected provider subcommand {verb!r} in help"


def test_provider_harnesses_lists_supported_values_from_code() -> None:
    _require_provider_command()
    registry = import_provider_cmd()
    list_fn = getattr(registry, "list_supported_harnesses", None)
    if list_fn is None:
        pytest.fail("provider_cmd.list_supported_harnesses is not implemented")

    result = _invoke("provider", "harnesses")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for harness in ("opencode", "codex", "claude", "gemini", "cursor"):
        assert harness in output.lower(), f"expected harness {harness!r} in output"
    code_rows = list_fn()
    assert code_rows, "list_supported_harnesses() must not be empty"
    for row in code_rows:
        name = row[0] if isinstance(row, (tuple, list)) else getattr(row, "name", None)
        assert name in output.lower()


# ---------------------------------------------------------------------------
# add / list round-trip — config.yaml + .env (D2)
# ---------------------------------------------------------------------------


def test_provider_add_writes_config_and_env_indexed_secret(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    entries = provider_entries(config)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["label"] == "nous"
    assert entry["url"] == NOUS_BASE_URL
    assert entry["harness"] == "opencode"
    assert entry["envIndex"] == 1

    env = read_env_file(tmp_path)
    assert env.get("LLM_PROVIDER_1") == "nous"


def test_provider_list_shows_registered_labels(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    add = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    assert add.exit_code == CLI_SUCCESS_EXIT_CODE, add.stdout + add.stderr

    listed = _invoke("provider", "list")
    output = _plain(listed.stdout + listed.stderr)
    assert listed.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "nous" in output


# ---------------------------------------------------------------------------
# edit / delete
# ---------------------------------------------------------------------------


def test_provider_edit_updates_url_in_config(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    add = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    assert add.exit_code == CLI_SUCCESS_EXIT_CODE

    updated_url = "https://inference-api.nousresearch.com/v2"
    edit = _invoke("provider", "edit", "nous", "--url", updated_url)
    assert edit.exit_code == CLI_SUCCESS_EXIT_CODE, edit.stdout + edit.stderr

    config = read_config(tmp_path)
    entries = provider_entries(config)
    assert len(entries) == 1
    assert entries[0]["url"] == updated_url


def test_provider_delete_removes_label_from_config(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    for label, url in (("alpha", CUSTOM_BASE_URL), ("beta", "https://beta.example/v1")):
        add = _invoke(
            "provider",
            "add",
            "--label",
            label,
            "--url",
            url,
            "--harness",
            "opencode",
        )
        assert add.exit_code == CLI_SUCCESS_EXIT_CODE

    delete = _invoke("provider", "delete", "alpha")
    assert delete.exit_code == CLI_SUCCESS_EXIT_CODE, delete.stdout + delete.stderr

    config = read_config(tmp_path)
    labels = {entry["label"] for entry in provider_entries(config)}
    assert labels == {"beta"}


def test_provider_edit_unknown_label_exits_nonzero(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke("provider", "edit", "missing", "--url", CUSTOM_BASE_URL)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "missing" in output.lower() or "unknown" in output.lower()


def test_provider_delete_unknown_label_exits_nonzero(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke("provider", "delete", "missing")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "missing" in output.lower() or "unknown" in output.lower()


def test_provider_add_rejects_duplicate_label(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    first = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE

    second = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    output = _plain(second.stdout + second.stderr)
    assert second.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "duplicate" in output.lower() or "already" in output.lower()


# ---------------------------------------------------------------------------
# Harness validation (D4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["nous", "acme"])
def test_provider_add_without_harness_fails_for_custom_provider(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    label: str,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        label,
        "--url",
        CUSTOM_BASE_URL,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "harness" in output.lower()
    for supported in ("opencode", "codex", "claude", "gemini", "cursor"):
        assert supported in output.lower()


def test_provider_add_rejects_unknown_harness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "not-a-real-harness",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "harness" in output.lower()


@pytest.mark.parametrize(
    ("label", "expected_harness"),
    sorted(BUILTIN_HARNESS_DEFAULTS.items()),
)
def test_builtin_provider_add_resolves_harness_without_flag(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    label: str,
    expected_harness: str,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        label,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    entries = provider_entries(config)
    match = next((entry for entry in entries if entry.get("label") == label), None)
    assert match is not None, f"built-in provider {label!r} missing from config"
    assert match.get("harness") == expected_harness


def test_provider_add_rejects_incompatible_harness_provider_pair(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        "anthropic",
        "--harness",
        "codex",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "incompatible" in output.lower() or "unsupported" in output.lower()


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "not-a-url",
        "ftp://files.example/v1",
        "relative/path",
    ],
)
def test_provider_add_rejects_non_http_url(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    bad_url: str,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        bad_url,
        "--harness",
        "opencode",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "url" in output.lower() or "http" in output.lower()


# ---------------------------------------------------------------------------
# Permanent env indices (D3)
# ---------------------------------------------------------------------------


def test_provider_delete_leaves_index_gap_and_never_reuses(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    for label in ("one", "two", "three"):
        add = _invoke(
            "provider",
            "add",
            "--label",
            label,
            "--url",
            f"https://{label}.example/v1",
            "--harness",
            "opencode",
        )
        assert add.exit_code == CLI_SUCCESS_EXIT_CODE

    before = read_config(tmp_path)
    before_indices = {entry["envIndex"] for entry in provider_entries(before)}
    assert before_indices == {1, 2, 3}

    delete = _invoke("provider", "delete", "two")
    assert delete.exit_code == CLI_SUCCESS_EXIT_CODE

    after_delete = read_config(tmp_path)
    remaining_indices = {entry["envIndex"] for entry in provider_entries(after_delete)}
    assert remaining_indices == {1, 3}
    assert 2 not in remaining_indices

    add_four = _invoke(
        "provider",
        "add",
        "--label",
        "four",
        "--url",
        "https://four.example/v1",
        "--harness",
        "opencode",
    )
    assert add_four.exit_code == CLI_SUCCESS_EXIT_CODE

    after_add = read_config(tmp_path)
    all_indices = sorted(entry["envIndex"] for entry in provider_entries(after_add))
    assert all_indices == [1, 3, 4]
    assert 2 not in all_indices


def test_provider_add_allocates_max_plus_one_even_with_gaps(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(
        tmp_path,
        config_body=yaml.safe_dump(
            {
                "providers": [
                    {"label": "kept", "harness": "opencode", "envIndex": 1},
                    {"label": "gap", "harness": "opencode", "envIndex": 5},
                ]
            }
        ),
    )
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    result = _invoke(
        "provider",
        "add",
        "--label",
        "newco",
        "--url",
        CUSTOM_BASE_URL,
        "--harness",
        "opencode",
    )
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    config = read_config(tmp_path)
    new_entry = next(entry for entry in provider_entries(config) if entry.get("label") == "newco")
    assert new_entry["envIndex"] == 6


# ---------------------------------------------------------------------------
# Seeding — PROVIDERS is seed data only
# ---------------------------------------------------------------------------


def test_provider_seed_imports_all_builtin_catalog_entries(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    registry = import_provider_cmd()
    seed_fn = getattr(registry, "seed_builtin_providers", None)
    if seed_fn is None:
        pytest.fail("provider_cmd.seed_builtin_providers is not implemented")

    seed_fn(tmp_path / ".mergecraft" / "config.yaml")
    config = read_config(tmp_path)
    labels = {entry["label"] for entry in provider_entries(config)}
    assert len(labels) == len(PROVIDERS)
    assert labels == set(PROVIDERS.keys())


def test_provider_registry_does_not_read_providers_dict_at_runtime(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    registry_mod = import_provider_cmd()
    seed_fn = getattr(registry_mod, "seed_builtin_providers", None)
    load_fn = getattr(registry_mod, "load_provider_registry", None)
    if seed_fn is None or load_fn is None:
        pytest.fail("provider registry seed/load helpers are not implemented")

    config_path = tmp_path / ".mergecraft" / "config.yaml"
    seed_fn(config_path)

    sentinel = "__registry_sentinel__"
    monkeypatch.setitem(PROVIDERS, sentinel, PROVIDERS["nous"])  # type: ignore[index]

    loaded = load_fn(config_path)
    lookup = getattr(loaded, "get", None) or getattr(loaded, "lookup", None)
    if lookup is None:
        pytest.fail("load_provider_registry result must expose get/lookup")
    assert lookup(sentinel) is None


def test_deleted_builtin_provider_is_not_reseeded_on_next_load(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    _require_provider_command()

    seed = _invoke("provider", "seed")
    if seed.exit_code == CLI_USAGE_EXIT_CODE:
        registry_mod = import_provider_cmd()
        seed_fn = getattr(registry_mod, "seed_builtin_providers", None)
        if seed_fn is None:
            pytest.fail("provider seeding is not implemented")
        seed_fn(tmp_path / ".mergecraft" / "config.yaml")
    else:
        assert seed.exit_code == CLI_SUCCESS_EXIT_CODE, seed.stdout + seed.stderr

    delete = _invoke("provider", "delete", "nous")
    assert delete.exit_code == CLI_SUCCESS_EXIT_CODE

    reload = _invoke("provider", "list")
    assert reload.exit_code == CLI_SUCCESS_EXIT_CODE
    output = _plain(reload.stdout + reload.stderr)
    assert "nous" not in output.split()


def test_unknown_registry_provider_does_not_default_to_opencode(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    registry_mod = import_provider_cmd()
    resolve_fn = getattr(registry_mod, "resolve_provider_harness", None)
    if resolve_fn is None:
        pytest.fail("provider_cmd.resolve_provider_harness is not implemented")

    with pytest.raises(Exception, match=r"harness|configuration|unknown|missing"):
        resolve_fn("typo-provider", harness=None)
