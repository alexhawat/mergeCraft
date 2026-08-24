"""RED tests for ``mergecraft model`` registry CLI (#479 / BC).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BC — test-creator. Pins add/list/delete per provider, unknown ``--provider`` failure,
config.yaml as model source of truth, optional ``LLM_PROVIDER_<N>_MODEL_<M>`` override (D2),
model ids without provider prefix, and permanent model indices (D3).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import typer
from tests.cli.support_provider_registry import (
    CUSTOM_BASE_URL,
    NOUS_BASE_URL,
    import_model_registry,
    model_id_value,
    model_index_value,
    provider_entry,
    provider_model_entries,
    read_config,
    read_env_file,
    scaffold_mergecraft_home,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

DEEPSEEK_V4 = "deepseek/deepseek-v4-flash"
TENCENT_HY3 = "tencent/hy3"
NOUS_PREFIXED_DEEPSEEK = f"nous/{DEEPSEEK_V4}"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str, **kwargs: object) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV, **kwargs)


def _require_model_command() -> None:
    """Fail until ``model`` is registered on the Typer app."""
    result = _invoke("model", "--help")
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail("mergecraft model is not registered yet")


def _register_provider(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    label: str = "nous",
    url: str = NOUS_BASE_URL,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
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
    assert add.exit_code == CLI_SUCCESS_EXIT_CODE, add.stdout + add.stderr


# ---------------------------------------------------------------------------
# CLI surface — verbs exist
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_help_lists_registry_verbs() -> None:
    _require_model_command()
    result = _invoke("model", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for verb in ("add", "list", "delete"):
        assert verb in output, f"expected model subcommand {verb!r} in help"


# ---------------------------------------------------------------------------
# add / list / delete round-trip — config.yaml source of truth (D2)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_add_writes_model_to_config_without_provider_prefix(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    result = _invoke("model", "add", "--provider", "nous", DEEPSEEK_V4)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    models = provider_model_entries(config, "nous")
    assert len(models) == 1
    stored_id = model_id_value(models[0])
    assert stored_id == DEEPSEEK_V4
    assert stored_id == models[0].get("id")
    assert not stored_id.startswith("nous/")
    assert NOUS_PREFIXED_DEEPSEEK not in stored_id
    assert model_index_value(models[0]) == 1


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_list_shows_registered_models(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    add = _invoke("model", "add", "--provider", "nous", DEEPSEEK_V4)
    assert add.exit_code == CLI_SUCCESS_EXIT_CODE, add.stdout + add.stderr

    listed = _invoke("model", "list")
    output = _plain(listed.stdout + listed.stderr)
    assert listed.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert DEEPSEEK_V4 in output
    assert "nous" in output.lower()


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_delete_removes_model_from_config(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    for model_id in (DEEPSEEK_V4, TENCENT_HY3):
        add = _invoke("model", "add", "--provider", "nous", model_id)
        assert add.exit_code == CLI_SUCCESS_EXIT_CODE

    delete = _invoke("model", "delete", "nous", DEEPSEEK_V4)
    assert delete.exit_code == CLI_SUCCESS_EXIT_CODE, delete.stdout + delete.stderr

    config = read_config(tmp_path)
    remaining = {model_id_value(row) for row in provider_model_entries(config, "nous")}
    assert remaining == {TENCENT_HY3}


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_add_does_not_write_env_by_default(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Config is the source of truth; env override is optional (D2)."""
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    result = _invoke("model", "add", "--provider", "nous", DEEPSEEK_V4)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    env = read_env_file(tmp_path)
    assert not any(key.startswith("LLM_PROVIDER_") and "_MODEL_" in key for key in env)


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_env_override_optional(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``LLM_PROVIDER_<N>_MODEL_<M>`` may override config when present (D2)."""
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    add = _invoke("model", "add", "--provider", "nous", DEEPSEEK_V4)
    assert add.exit_code == CLI_SUCCESS_EXIT_CODE

    override_id = "tencent/hy3"
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_PROVIDER_1_MODEL_1=tencent/hy3\n", encoding="utf-8")

    listed = _invoke("model", "list")
    output = _plain(listed.stdout + listed.stderr)
    assert listed.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert override_id in output


# ---------------------------------------------------------------------------
# Unknown provider must fail (#479)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_add_unknown_provider_fails_and_names_registered_providers(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    for label, url in (("nous", NOUS_BASE_URL), ("acme", CUSTOM_BASE_URL)):
        add_provider = _invoke(
            "provider",
            "add",
            "--label",
            label,
            "--url",
            url,
            "--harness",
            "opencode",
        )
        assert add_provider.exit_code == CLI_SUCCESS_EXIT_CODE
    _require_model_command()

    result = _invoke("model", "add", "--provider", "nuos", DEEPSEEK_V4)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "nuos" in lowered or "unknown" in lowered or "not registered" in lowered
    assert "nous" in lowered
    assert "acme" in lowered

    config = read_config(tmp_path)
    assert provider_model_entries(config, "nuos") == []


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_delete_unknown_provider_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    result = _invoke("model", "delete", "missing", DEEPSEEK_V4)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "missing" in output.lower() or "unknown" in output.lower()


# ---------------------------------------------------------------------------
# Duplicate rejection
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_add_rejects_duplicate_model_on_same_provider(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    first = _invoke("model", "add", "--provider", "nous", DEEPSEEK_V4)
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE

    second = _invoke("model", "add", "--provider", "nous", DEEPSEEK_V4)
    output = _plain(second.stdout + second.stderr)
    assert second.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "duplicate" in output.lower() or "already" in output.lower()

    config = read_config(tmp_path)
    assert len(provider_model_entries(config, "nous")) == 1


# ---------------------------------------------------------------------------
# Interactive picker when ``--provider`` omitted (#479)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_add_without_provider_prompts_registered_providers(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    for label, url in (("nous", NOUS_BASE_URL), ("acme", CUSTOM_BASE_URL)):
        add_provider = _invoke(
            "provider",
            "add",
            "--label",
            label,
            "--url",
            url,
            "--harness",
            "opencode",
        )
        assert add_provider.exit_code == CLI_SUCCESS_EXIT_CODE
    _require_model_command()

    prompted: list[str] = []

    def _fake_prompt(message: str, **kwargs: object) -> str:
        prompted.append(message)
        return "nous"

    monkeypatch.setattr(typer, "prompt", _fake_prompt)

    result = _invoke("model", "add", DEEPSEEK_V4)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert prompted, "expected interactive provider picker when --provider is omitted"
    prompt_text = prompted[0].lower()
    assert "provider" in prompt_text
    assert "nous" in prompt_text or "acme" in prompt_text

    config = read_config(tmp_path)
    assert model_id_value(provider_model_entries(config, "nous")[0]) == DEEPSEEK_V4


# ---------------------------------------------------------------------------
# Permanent model indices (D3) — mirror provider envIndex rules
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_delete_leaves_model_index_gap_and_never_reuses(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    for model_id in (DEEPSEEK_V4, TENCENT_HY3, "meta/llama-3"):
        add = _invoke("model", "add", "--provider", "nous", model_id)
        assert add.exit_code == CLI_SUCCESS_EXIT_CODE

    before = read_config(tmp_path)
    before_indices = {
        model_index_value(row)
        for row in provider_model_entries(before, "nous")
        if model_index_value(row) is not None
    }
    assert before_indices == {1, 2, 3}

    delete = _invoke("model", "delete", "nous", TENCENT_HY3)
    assert delete.exit_code == CLI_SUCCESS_EXIT_CODE

    after_delete = read_config(tmp_path)
    remaining_indices = {
        model_index_value(row)
        for row in provider_model_entries(after_delete, "nous")
        if model_index_value(row) is not None
    }
    assert remaining_indices == {1, 3}
    assert 2 not in remaining_indices

    add_four = _invoke("model", "add", "--provider", "nous", "openai/gpt-4o-mini")
    assert add_four.exit_code == CLI_SUCCESS_EXIT_CODE

    after_add = read_config(tmp_path)
    all_indices = sorted(
        idx
        for row in provider_model_entries(after_add, "nous")
        for idx in [model_index_value(row)]
        if idx is not None
    )
    assert all_indices == [1, 3, 4]
    assert 2 not in all_indices


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_model_add_allocates_max_plus_one_model_index_with_gaps(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scaffold_mergecraft_home(
        tmp_path,
        config_body=(
            "providers:\n"
            "  - label: nous\n"
            "    url: https://inference-api.nousresearch.com/v1\n"
            "    harness: opencode\n"
            "    envIndex: 1\n"
            "    models:\n"
            "      - id: deepseek/deepseek-v4-flash\n"
            "        modelIndex: 1\n"
            "      - id: tencent/hy3\n"
            "        modelIndex: 5\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    _require_model_command()

    result = _invoke("model", "add", "--provider", "nous", "meta/llama-3")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    config = read_config(tmp_path)
    new_row = next(
        row
        for row in provider_model_entries(config, "nous")
        if model_id_value(row) == "meta/llama-3"
    )
    assert model_index_value(new_row) == 6


# ---------------------------------------------------------------------------
# Unit — model index allocation helpers
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_allocate_model_index_returns_max_plus_one() -> None:
    registry = import_model_registry()
    allocate = getattr(registry, "allocate_model_index", None)
    if allocate is None:
        pytest.fail("model_registry.allocate_model_index is not implemented")

    assert allocate([{"modelIndex": 1}, {"modelIndex": 3}]) == 4
    assert allocate([{"modelIndex": 7}]) == 8
    assert allocate([]) == 1


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_allocate_model_index_never_reuses_gaps() -> None:
    registry = import_model_registry()
    allocate = getattr(registry, "allocate_model_index", None)
    if allocate is None:
        pytest.fail("model_registry.allocate_model_index is not implemented")

    # Gap at 2 must not be recycled — always max + 1.
    assert allocate([{"modelIndex": 1}, {"modelIndex": 5}]) == 6


@pytest.mark.xfail(reason="green after BC impl", strict=False)
def test_stored_model_rows_use_id_without_provider_prefix_field(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Full provider prefix is assembled at resolve time, never stored (#479)."""
    _register_provider(tmp_path, monkeypatch)
    _require_model_command()

    result = _invoke("model", "add", "--provider", "nous", NOUS_PREFIXED_DEEPSEEK)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    entry = provider_entry(config, "nous")
    assert entry is not None
    models = provider_model_entries(config, "nous")
    assert len(models) == 1
    stored = model_id_value(models[0])
    assert stored == DEEPSEEK_V4
    assert stored != NOUS_PREFIXED_DEEPSEEK
