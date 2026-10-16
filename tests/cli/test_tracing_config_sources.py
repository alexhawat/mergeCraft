"""``config tracing`` reads the same config files as ``doctor`` and ``config explain`` (#919).

``mergecraft config tracing`` was the last read view that computed its own
config path from ``--config`` / ``MERGECRAFT_CONFIG``. It therefore disagreed
with ``doctor``, ``config show/explain`` and the layered loader about whether
``.mergecraft/config.local.yaml`` contributes, and about a missing
``MERGECRAFT_CONFIG`` file. These tests pin the shared view without touching the
flag -> env -> YAML ordering.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.config_precedence import explain_setting
from mergecraft.cli.doctor_cmd import _config_probe
from mergecraft.cli.tracing_precedence import resolve_tracing_settings
from mergecraft.config.layered import resolve_config_sources

_RUNNER = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TERM = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "400"}
_TRACING_ENV = (
    "MERGECRAFT_CONFIG",
    "GITHUB_ACTIONS",
    "MERGECRAFT_TRACING",
    "MERGECRAFT_TRACING_TO",
    "MERGECRAFT_TRACE_DIR",
    "MERGECRAFT_LOGFIRE_TOKEN",
    "MERGECRAFT_OTEL_ENDPOINT",
    "MERGECRAFT_TRACING_REGION",
    "MERGECRAFT_TRACING_CONTENT",
    "MERGECRAFT_TRACING_PROJECT",
    "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TRACING_ENV:
        monkeypatch.delenv(key, raising=False)


def _write_repo(
    root: Path,
    *,
    committed: str = "tracing:\n  enabled: false\n",
    local: str | None = "tracing:\n  enabled: true\n  sinks:\n    - type: otel\n",
) -> None:
    config_dir = root / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(committed, encoding="utf-8")
    if local is not None:
        (config_dir / "config.local.yaml").write_text(local, encoding="utf-8")


def _config_tracing(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *extra: str,
    env: dict[str, str] | None = None,
) -> str:
    from mergecraft.cli.app import app

    monkeypatch.chdir(root)
    result = _RUNNER.invoke(app, ["config", "tracing", *extra], env={**_TERM, **(env or {})})
    assert result.exit_code == 0, result.stdout + result.stderr
    return _ANSI.sub("", result.stdout + result.stderr)


def test_the_local_overlay_contributes_to_the_resolved_yaml_layer(tmp_path: Path) -> None:
    _write_repo(tmp_path)

    resolved = resolve_tracing_settings(cli_args=[], env={}, config_root=tmp_path)

    assert resolved["enabled"] is True, "config.local.yaml enables tracing off CI"
    assert resolved["tracing_to"] == "otel"


def test_config_tracing_lists_the_files_doctor_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path)

    rendered = _config_tracing(tmp_path, monkeypatch)
    sources = resolve_config_sources(tmp_path)
    doctor = _config_probe(tmp_path)

    assert [path.name for path in sources.files] == ["config.yaml", "config.local.yaml"]
    for path in sources.files:
        assert path.name in rendered, f"config tracing omits {path.name}: {rendered!r}"
        assert path.name in doctor.detail, f"doctor omits {path.name}: {doctor.detail!r}"


def test_config_tracing_and_config_explain_agree_about_the_local_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path)

    explained = explain_setting("tracing.enabled", cwd=tmp_path)
    rendered = _config_tracing(tmp_path, monkeypatch)

    assert explained["layers"]["yaml"] is True
    assert re.search(r"status\s+enabled", rendered), rendered
    assert not re.search(r"status\s+disabled", rendered), rendered


def test_without_a_local_overlay_only_the_committed_file_contributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path, local=None)

    rendered = _config_tracing(tmp_path, monkeypatch)

    assert "config.yaml" in rendered
    assert "config.local.yaml" not in rendered
    assert re.search(r"status\s+disabled", rendered), rendered


def test_the_local_overlay_is_ignored_on_ci_like_the_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    rendered = _config_tracing(tmp_path, monkeypatch, env={"GITHUB_ACTIONS": "true"})
    sources = resolve_config_sources(tmp_path)

    assert [path.name for path in sources.files] == ["config.yaml"]
    assert "config.local.yaml" not in rendered
    assert re.search(r"status\s+disabled", rendered), rendered


def test_a_missing_mergecraft_config_is_reported_the_way_doctor_reports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path, local=None)
    missing = tmp_path / "nope.yaml"
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(missing))

    doctor = _config_probe(tmp_path)
    rendered = _config_tracing(
        tmp_path, monkeypatch, env={"MERGECRAFT_CONFIG": str(missing)}
    ).lower()

    assert "mergecraft_config" in doctor.detail.lower()
    assert "mergecraft_config" in rendered, rendered
    assert "nope.yaml" in rendered, rendered
    assert "does not exist" in rendered, rendered
    assert "config.yaml" in rendered, "the committed file still contributes"


def test_an_existing_mergecraft_config_is_the_sole_contributor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path)
    explicit = tmp_path / "elsewhere.yaml"
    explicit.write_text("tracing:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(explicit))

    rendered = _config_tracing(tmp_path, monkeypatch, env={"MERGECRAFT_CONFIG": str(explicit)})

    assert "elsewhere.yaml" in rendered
    assert "config.local.yaml" not in rendered


def test_an_explicit_config_flag_wins_before_the_shared_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repo(tmp_path)
    flagged = tmp_path / "flagged.yaml"
    flagged.write_text("tracing:\n  enabled: false\n", encoding="utf-8")

    rendered = _config_tracing(tmp_path, monkeypatch, "--config", str(flagged))

    assert "flagged.yaml" in rendered
    assert "config.local.yaml" not in rendered
    assert re.search(r"status\s+disabled", rendered), rendered


@pytest.mark.parametrize(
    ("env", "cli_args", "expected"),
    [
        ({"MERGECRAFT_TRACING_TO": "logfire"}, [], "logfire"),
        ({"MERGECRAFT_TRACING_TO": "logfire"}, ["--tracing-to", "local_files"], "local_files"),
        ({}, [], "otel"),
    ],
    ids=["env-over-yaml", "flag-over-env", "yaml-when-nothing-above"],
)
def test_flag_env_yaml_precedence_is_unchanged(
    tmp_path: Path,
    env: dict[str, str],
    cli_args: list[str],
    expected: str,
) -> None:
    _write_repo(tmp_path)

    resolved = resolve_tracing_settings(cli_args=cli_args, env=env, config_root=tmp_path)

    assert resolved["tracing_to"] == expected


def test_not_passing_a_config_root_keeps_todays_behaviour(tmp_path: Path) -> None:
    """The live sink path does not read YAML it was never handed (no silent widening)."""
    _write_repo(tmp_path)

    resolved = resolve_tracing_settings(cli_args=[], env={"__SENTINEL__": "1"}, config_path=None)

    assert resolved["enabled"] is False
    assert "tracing_to" not in resolved
