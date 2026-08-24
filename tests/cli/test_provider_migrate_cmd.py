"""RED tests for ``mergecraft provider migrate`` (#483 / BF).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BF — test-creator. Pins dry-run default, secret-safe diff, ``--apply`` idempotency,
config/secret split enforcement (D2), legacy shim precedence (D7), and Bedrock/Vertex
``cloud_chain`` multi-secret migration (D10).
"""

from __future__ import annotations

import re
import warnings
from typing import TYPE_CHECKING

import pytest
import yaml
from tests.cli.support_provider_registry import (
    AUTH_KIND_CLOUD_CHAIN,
    BEDROCK_LEGACY_CONFIG_KEYS,
    BEDROCK_LEGACY_SECRET_KEYS,
    BF_XFAIL,
    LEGACY_API_KEY_MIGRATIONS,
    LEGACY_STRUCTURE_IN_ENV,
    NOUS_BASE_URL,
    VERTEX_LEGACY_CONFIG_KEYS,
    VERTEX_LEGACY_SECRET_KEYS,
    assert_output_never_contains_secret,
    config_text,
    env_text,
    indexed_env_key,
    provider_entries,
    read_config,
    read_env_file,
    scaffold_mergecraft_home,
    stub_mergecraft_env,
    write_env_pairs,
    write_provider_entry,
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

_OPENAI_LEGACY_SECRET = "sk-openai-legacy-SECRET12345"
_NOUS_LEGACY_SECRET = "nous-legacy-SECRET67890"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _setup_repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


@BF_XFAIL
def test_provider_help_lists_migrate_verb() -> None:
    result = _invoke("provider", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "migrate" in output


@BF_XFAIL
def test_provider_migrate_help_documents_apply_flag() -> None:
    result = _invoke("provider", "migrate", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "apply" in output
    assert "dry" in output or "default" in output


# ---------------------------------------------------------------------------
# Dry-run default — prints names, never secret values (D2 / #483)
# ---------------------------------------------------------------------------


@BF_XFAIL
def test_provider_migrate_default_is_dry_run_no_writes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(tmp_path, {"OPENAI_API_KEY": _OPENAI_LEGACY_SECRET})

    before_env = env_text(tmp_path)
    before_cfg = config_text(tmp_path)

    result = _invoke("provider", "migrate")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert env_text(tmp_path) == before_env
    assert config_text(tmp_path) == before_cfg
    assert provider_entries(read_config(tmp_path)) == []


@pytest.mark.parametrize(
    ("legacy_key", "provider_label", "suffix"),
    [
        (legacy, label, suffix)
        for legacy, (label, suffix) in sorted(LEGACY_API_KEY_MIGRATIONS.items())
    ],
)
@BF_XFAIL
def test_provider_migrate_dry_run_prints_key_names_not_secret_values(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    legacy_key: str,
    provider_label: str,
    suffix: str,
) -> None:
    secret = f"{legacy_key.lower()}-super-secret-value-XY"
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(tmp_path, {legacy_key: secret})

    result = _invoke("provider", "migrate")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert legacy_key in output
    assert indexed_env_key(1, suffix) in output or f"LLM_PROVIDER_1_{suffix}" in output
    assert provider_label in output.lower()
    assert_output_never_contains_secret(output, secret)


@BF_XFAIL
def test_provider_migrate_dry_run_shows_fingerprint_not_full_secret(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(tmp_path, {"OPENAI_API_KEY": _OPENAI_LEGACY_SECRET})

    result = _invoke("provider", "migrate")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert_output_never_contains_secret(output, _OPENAI_LEGACY_SECRET)
    assert "2345" in output or "fingerprint" in output.lower() or "…" in output


# ---------------------------------------------------------------------------
# ``--apply`` writes indexed keys + config; idempotent (D2)
# ---------------------------------------------------------------------------


@BF_XFAIL
def test_provider_migrate_apply_writes_provider_config_and_indexed_secrets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(
        tmp_path,
        {
            "OPENAI_API_KEY": _OPENAI_LEGACY_SECRET,
            "NOUS_API_KEY": _NOUS_LEGACY_SECRET,
            "NOUS_BASE_URL": NOUS_BASE_URL,
        },
    )

    dry = _invoke("provider", "migrate")
    assert dry.exit_code == CLI_SUCCESS_EXIT_CODE, dry.stdout + dry.stderr

    apply = _invoke("provider", "migrate", "--apply")
    output = _plain(apply.stdout + apply.stderr)
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    entries = provider_entries(config)
    labels = {str(entry.get("label", "")).lower() for entry in entries}
    assert "openai" in labels
    assert "nous" in labels

    env = read_env_file(tmp_path)
    assert env.get("LLM_PROVIDER_1") == "openai"
    assert env.get(indexed_env_key(1, "API_KEY")) == _OPENAI_LEGACY_SECRET
    assert env.get("LLM_PROVIDER_2") == "nous"
    assert env.get(indexed_env_key(2, "API_KEY")) == _NOUS_LEGACY_SECRET

    nous_entry = next(entry for entry in entries if entry.get("label") == "nous")
    assert nous_entry.get("url") == NOUS_BASE_URL

    cfg_lower = config_text(tmp_path).lower()
    assert _OPENAI_LEGACY_SECRET.lower() not in cfg_lower
    assert _NOUS_LEGACY_SECRET.lower() not in cfg_lower


@BF_XFAIL
def test_provider_migrate_apply_idempotent_second_run_is_noop(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(tmp_path, {"DEEPSEEK_API_KEY": "deepseek-migrate-key-abc"})

    first = _invoke("provider", "migrate", "--apply")
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE, first.stdout + first.stderr
    after_first_env = env_text(tmp_path)
    after_first_cfg = config_text(tmp_path)

    second = _invoke("provider", "migrate", "--apply")
    output = _plain(second.stdout + second.stderr).lower()
    assert second.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert env_text(tmp_path) == after_first_env
    assert config_text(tmp_path) == after_first_cfg
    assert "no changes" in output or "already migrated" in output or "noop" in output


@BF_XFAIL
def test_provider_migrate_apply_only_fills_missing_after_partial_manual(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_provider_entry(
        tmp_path,
        label="openai",
        env_index=1,
        harness="codex",
        auth_kind="device_code",
    )
    write_env_pairs(
        tmp_path,
        {
            "LLM_PROVIDER_1": "openai",
            "OPENAI_API_KEY": _OPENAI_LEGACY_SECRET,
        },
    )

    result = _invoke("provider", "migrate", "--apply")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr

    env = read_env_file(tmp_path)
    assert env.get(indexed_env_key(1, "API_KEY")) == _OPENAI_LEGACY_SECRET
    assert len(provider_entries(read_config(tmp_path))) == 1


# ---------------------------------------------------------------------------
# Config / secret split enforced (D2)
# ---------------------------------------------------------------------------


@BF_XFAIL
def test_provider_migrate_config_yaml_never_contains_credential_values(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(
        tmp_path,
        {
            "OPENAI_API_KEY": _OPENAI_LEGACY_SECRET,
            "CURSOR_API_KEY": "cursor-secret-VALUE999",
        },
    )

    apply = _invoke("provider", "migrate", "--apply")
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, apply.stdout + apply.stderr

    raw = config_text(tmp_path)
    assert _OPENAI_LEGACY_SECRET not in raw
    assert "cursor-secret-VALUE999" not in raw
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict)
    for entry in provider_entries(parsed):
        for _key, value in entry.items():
            if isinstance(value, str):
                assert _OPENAI_LEGACY_SECRET not in value
                assert "cursor-secret-VALUE999" not in value


@BF_XFAIL
def test_provider_migrate_env_never_contains_harness_or_url_structure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(
        tmp_path,
        {
            "NOUS_API_KEY": _NOUS_LEGACY_SECRET,
            "NOUS_BASE_URL": NOUS_BASE_URL,
        },
    )

    apply = _invoke("provider", "migrate", "--apply")
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, apply.stdout + apply.stderr

    env_blob = env_text(tmp_path).lower()
    for token in LEGACY_STRUCTURE_IN_ENV:
        assert f"{token}=" not in env_blob
    assert "harness:" not in env_blob
    assert NOUS_BASE_URL not in env_blob or "url=" not in env_blob


@BF_XFAIL
def test_provider_migrate_ambiguous_custom_base_url_refuses_or_prompts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(
        tmp_path,
        {"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL": "https://ambiguous.example.invalid/v1"},
    )

    result = _invoke("provider", "migrate")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "custom" in output or "mergecraft_custom_provider_base_url" in output
    assert "label" in output or "todo" in output or "ambiguous" in output
    assert provider_entries(read_config(tmp_path)) == []
    assert "LLM_PROVIDER_1" not in read_env_file(tmp_path)


@BF_XFAIL
def test_provider_migrate_deterministic_index_allocation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_env_pairs(
        tmp_path,
        {
            "OPENAI_API_KEY": "openai-key-one",
            "DEEPSEEK_API_KEY": "deepseek-key-two",
        },
    )

    first = _invoke("provider", "migrate", "--apply")
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE, first.stdout + first.stderr
    first_env = read_env_file(tmp_path)

    scaffold_mergecraft_home(tmp_path)
    write_env_pairs(
        tmp_path,
        {
            "OPENAI_API_KEY": "openai-key-one",
            "DEEPSEEK_API_KEY": "deepseek-key-two",
        },
    )

    second = _invoke("provider", "migrate", "--apply")
    assert second.exit_code == CLI_SUCCESS_EXIT_CODE, second.stdout + second.stderr
    second_env = read_env_file(tmp_path)

    assert first_env.get("LLM_PROVIDER_1") == second_env.get("LLM_PROVIDER_1") == "openai"
    assert first_env.get("LLM_PROVIDER_2") == second_env.get("LLM_PROVIDER_2") == "deepseek"


# ---------------------------------------------------------------------------
# Bedrock / Vertex ``cloud_chain`` — one index, multi-secret (D10)
# ---------------------------------------------------------------------------


@BF_XFAIL
def test_provider_migrate_bedrock_maps_multi_secret_under_one_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    legacy = {
        "AWS_ACCESS_KEY_ID": "AKIA-BEDROCK-TEST",
        "AWS_SECRET_ACCESS_KEY": "bedrock-secret-KEY-XY",
        "AWS_REGION": "us-east-1",
    }
    write_env_pairs(tmp_path, legacy)

    apply = _invoke("provider", "migrate", "--apply")
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, apply.stdout + apply.stderr

    config = read_config(tmp_path)
    bedrock = next(
        (entry for entry in provider_entries(config) if entry.get("label") == "bedrock"),
        None,
    )
    assert bedrock is not None
    assert bedrock.get("authKind") == AUTH_KIND_CLOUD_CHAIN
    env_index = int(bedrock["envIndex"])

    env = read_env_file(tmp_path)
    assert env.get(f"LLM_PROVIDER_{env_index}") == "bedrock"
    for suffix in BEDROCK_LEGACY_SECRET_KEYS:
        assert env.get(indexed_env_key(env_index, suffix)) == legacy[suffix]
    assert indexed_env_key(env_index, "API_KEY") not in env

    cfg_text = config_text(tmp_path)
    assert "us-east-1" in cfg_text or any(key in cfg_text for key in BEDROCK_LEGACY_CONFIG_KEYS)


@BF_XFAIL
def test_provider_migrate_bedrock_copies_aws_vars_leaves_originals_in_place(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    legacy = {
        "AWS_ACCESS_KEY_ID": "AKIA-SHARED-ORIGINAL",
        "AWS_SECRET_ACCESS_KEY": "shared-secret-ORIGINAL",
    }
    write_env_pairs(tmp_path, legacy)

    dry = _invoke("provider", "migrate")
    dry_output = _plain(dry.stdout + dry.stderr).lower()
    assert dry.exit_code == CLI_SUCCESS_EXIT_CODE, dry_output
    assert "leave" in dry_output or "copy" in dry_output or "original" in dry_output

    apply = _invoke("provider", "migrate", "--apply")
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, apply.stdout + apply.stderr

    env = read_env_file(tmp_path)
    assert env.get("AWS_ACCESS_KEY_ID") == legacy["AWS_ACCESS_KEY_ID"]
    assert env.get("AWS_SECRET_ACCESS_KEY") == legacy["AWS_SECRET_ACCESS_KEY"]


@BF_XFAIL
def test_provider_migrate_vertex_maps_credentials_under_one_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    cred_path = "/tmp/vertex-sa.json"
    write_env_pairs(
        tmp_path,
        {
            "GOOGLE_APPLICATION_CREDENTIALS": cred_path,
            "GOOGLE_CLOUD_PROJECT": "mergecraft-test",
            "VERTEX_LOCATION": "us-central1",
        },
    )

    apply = _invoke("provider", "migrate", "--apply")
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, apply.stdout + apply.stderr

    config = read_config(tmp_path)
    vertex = next(
        (entry for entry in provider_entries(config) if entry.get("label") == "vertex"),
        None,
    )
    assert vertex is not None
    env_index = int(vertex["envIndex"])
    env = read_env_file(tmp_path)
    assert env.get(f"LLM_PROVIDER_{env_index}") == "vertex"
    for suffix in VERTEX_LEGACY_SECRET_KEYS:
        assert env.get(indexed_env_key(env_index, suffix)) == cred_path
    assert indexed_env_key(env_index, "API_KEY") not in env

    cfg_text = config_text(tmp_path)
    assert any(key.lower() in cfg_text.lower() for key in VERTEX_LEGACY_CONFIG_KEYS)


# ---------------------------------------------------------------------------
# Legacy shim — registry key wins; warning once per process (D7)
# ---------------------------------------------------------------------------


@BF_XFAIL
def test_legacy_env_registry_key_wins_with_single_deprecation_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    write_provider_entry(
        tmp_path,
        label="openai",
        env_index=1,
        harness="codex",
        auth_kind="device_code",
    )
    registry_secret = "registry-openai-WINS-KEY"
    legacy_secret = "legacy-openai-LOSES-KEY"
    write_env_pairs(
        tmp_path,
        {
            "LLM_PROVIDER_1": "openai",
            "LLM_PROVIDER_1_API_KEY": registry_secret,
            "OPENAI_API_KEY": legacy_secret,
        },
    )

    module = __import__(
        "mergecraft.cli.provider_cmd",
        fromlist=["resolve_indexed_credential"],
    )
    resolve_fn = getattr(module, "resolve_indexed_credential", None)
    if resolve_fn is None:
        pytest.fail("provider_cmd.resolve_indexed_credential is not implemented")

    config = read_config(tmp_path)
    entry = provider_entries(config)[0]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = resolve_fn(entry)
        resolved_again = resolve_fn(entry)

    assert resolved == registry_secret
    assert resolved != legacy_secret
    deprecation = [item for item in caught if issubclass(item.category, DeprecationWarning)]
    assert len(deprecation) == 1
    message = str(deprecation[0].message).lower()
    assert "openai_api_key" in message or "legacy" in message
    assert "ignored" in message or "wins" in message or "prefer" in message
    assert resolved_again == registry_secret
