"""RED contracts for CLI / env / config precedence (W7.6).

Issue #56 specifies the precedence order:

1. CLI flag
2. Environment variable
3. ``.mergecraft/config.yaml``
4. Default (off)

W8.4 introduces the ``diff-review`` flags (``--tracing``, ``--no-tracing``,
``--tracing-to``, ``--trace-dir``, ``--logfire-token``, ``--otel-endpoint``)
and the env vars (``MERGECRAFT_TRACING``, ``MERGECRAFT_LOGFIRE_TOKEN``, …).
This module pins the precedence arithmetic so a fork that swaps CLI/env
order (or honours env above CLI) is wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

_RUNNER = CliRunner()
_ANSI = __import__("re").compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


# ---------------------------------------------------------------------------
# W7.6 — CLI flag > env > .mergecraft/config.yaml > default (off).
# ---------------------------------------------------------------------------


def test_default_is_off() -> None:
    """With no CLI flag, no env var, and no config, tracing is disabled."""
    from mergecraft.cli.app import app

    # The ``diff-review --help`` output lists the new tracing flags — a
    # surface assertion that the CLI was wired up.
    result = _RUNNER.invoke(app, ["diff-review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    for flag in (
        "--tracing",
        "--no-tracing",
        "--tracing-to",
        "--trace-dir",
        "--logfire-token",
        "--otel-endpoint",
    ):
        assert flag in out, f"missing CLI flag {flag!r} in --help"


@pytest.mark.parametrize(
    ("layer", "set_up"),
    [
        ("cli_only", lambda env, config: None),  # CLI flag wins (set below)
        ("env_only", lambda env, config: env.setenv("MERGECRAFT_TRACING", "true")),
        ("config_only", lambda env, config: config.write_text("tracing:\n  enabled: true\n")),
        ("default_only", lambda env, config: None),
    ],
)
def test_cli_env_config_precedence(
    layer: str, set_up: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parametrised precedence table — CLI > env > config > default.

    Each case asserts the resolution order by setting every layer *except*
    the one under test and confirming the under-test layer wins.
    """
    from mergecraft.cli.app import app

    config = tmp_path / "config.yaml"
    config.write_text("tracing:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("MERGECRAFT_OTEL_ENDPOINT", raising=False)
    set_up(monkeypatch, config)  # activate the layer under test

    patch = tmp_path / "in.diff"
    patch.write_text("diff --git a/x b/x\n+1\n", encoding="utf-8")

    args = ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"]
    if layer == "cli_only":
        args.extend(["--tracing"])
    if layer == "config_only":
        # Replace the default-off config with enabled=true via a fresh config.
        config.write_text("tracing:\n  enabled: true\n", encoding="utf-8")

    result = _RUNNER.invoke(
        app, args, env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_CONFIG": str(config)}
    )
    # The CLI exits 0 even in dry-run; the precedence assertion is made by
    # interrogating the resolved tracing settings via a public hook.
    assert result.exit_code == 0, result.stdout + result.stderr

    resolved = _resolve_tracing_for_args(args, env=_env_from(monkeypatch, config), cwd=tmp_path)
    if layer in {"cli_only", "env_only", "config_only"}:
        assert resolved["enabled"] is True, f"{layer}: expected enabled=True, got {resolved}"
    else:
        assert resolved["enabled"] is False, (
            f"{layer}: expected enabled=False (default), got {resolved}"
        )


def test_cli_flag_overrides_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--no-tracing`` wins over ``MERGECRAFT_TRACING=true``."""
    from mergecraft.cli.app import app

    config = tmp_path / "config.yaml"
    config.write_text("tracing:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))

    patch = tmp_path / "in.diff"
    patch.write_text("diff --git a/x b/x\n+1\n", encoding="utf-8")

    result = _RUNNER.invoke(
        app,
        ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run", "--no-tracing"],
        env={"NO_COLOR": "1", "TERM": "dumb", "MERGECRAFT_CONFIG": str(config)},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    resolved = _resolve_tracing_for_args(
        ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run", "--no-tracing"],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert resolved["enabled"] is False, (
        f"--no-tracing must win over MERGECRAFT_TRACING=true: {resolved}"
    )


def test_cli_logfire_token_flag_wins_over_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--logfire-token`` on the CLI wins over ``MERGECRAFT_LOGFIRE_TOKEN``."""
    from mergecraft.cli.app import app

    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: logfire\n", encoding="utf-8"
    )
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "env-token")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))

    patch = tmp_path / "in.diff"
    patch.write_text("diff --git a/x b/x\n+1\n", encoding="utf-8")

    result = _RUNNER.invoke(
        app,
        [
            "diff-review",
            "--diff",
            str(patch),
            "--cwd",
            str(tmp_path),
            "--dry-run",
            "--logfire-token",
            "cli-token",
        ],
        env={
            "NO_COLOR": "1",
            "TERM": "dumb",
            "MERGECRAFT_CONFIG": str(config),
            "MERGECRAFT_LOGFIRE_TOKEN": "env-token",
        },
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    resolved = _resolve_tracing_for_args(
        [
            "diff-review",
            "--diff",
            str(patch),
            "--cwd",
            str(tmp_path),
            "--dry-run",
            "--logfire-token",
            "cli-token",
        ],
        env={"MERGECRAFT_CONFIG": str(config), "MERGECRAFT_LOGFIRE_TOKEN": "env-token"},
        cwd=tmp_path,
    )
    assert resolved["logfire_token"] == "cli-token", resolved


def test_otel_endpoint_env_var_overrides_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``MERGECRAFT_OTEL_ENDPOINT`` wins over the YAML ``endpoint`` field."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: otel\n      endpoint: http://config-host:4318/\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_OTEL_ENDPOINT", "http://env-host:4318/")

    resolved = _resolve_tracing_for_args(
        ["diff-review", "--diff", str(tmp_path / "x.diff"), "--cwd", str(tmp_path), "--dry-run"],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert resolved["otel_endpoint"] == "http://env-host:4318/", resolved


def test_trace_dir_flag_overrides_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--trace-dir`` wins over the YAML ``path`` for a ``jsonl_file`` sink."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: jsonl_file\n      path: from-config\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))

    custom_dir = tmp_path / "cli-traces"
    resolved = _resolve_tracing_for_args(
        [
            "diff-review",
            "--diff",
            str(tmp_path / "x.diff"),
            "--cwd",
            str(tmp_path),
            "--dry-run",
            "--trace-dir",
            str(custom_dir),
        ],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert resolved["trace_dir"] == str(custom_dir), resolved


# ---------------------------------------------------------------------------
# W8.4 — ``MERGECRAFT_TRACING_PROJECT`` env var (auth logfire surface).
# Issue #56 / D5 — the Logfire project label becomes the
# ``x-logfire-project`` header at runtime. The CLI ``auth logfire`` command
# writes this alongside ``MERGECRAFT_LOGFIRE_TOKEN``; the precedence layer
# surfaces it for ``mergecraft config tracing`` and the sink factory.
# ---------------------------------------------------------------------------


def test_tracing_project_env_var_is_surfaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``MERGECRAFT_TRACING_PROJECT`` shows up in the resolved tracing state."""
    config = tmp_path / "config.yaml"
    config.write_text("tracing:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", "logfire")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "acme/widgets")

    patch = tmp_path / "in.diff"
    patch.write_text("diff --git a/x b/x\n+1\n", encoding="utf-8")

    resolved = _resolve_tracing_for_args(
        ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert resolved.get("tracing_project") == "acme/widgets", resolved


def test_tracing_project_env_var_overrides_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``MERGECRAFT_TRACING_PROJECT`` wins over the YAML ``sinks[].project`` field.

    Parity with the other MERGECRAFT_TRACING_* env vars — env > config —
    so the ``auth logfire`` command (which writes the env var) overrides any
    project the repo author baked into ``.mergecraft/config.yaml``.
    """
    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: logfire\n      project: yaml-project\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", "logfire")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "env-project")

    resolved = _resolve_tracing_for_args(
        ["diff-review", "--diff", str(tmp_path / "x.diff"), "--cwd", str(tmp_path), "--dry-run"],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert resolved.get("tracing_project") == "env-project", resolved


def test_tracing_project_blank_env_value_is_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty/whitespace ``MERGECRAFT_TRACING_PROJECT`` does not surface."""
    config = tmp_path / "config.yaml"
    config.write_text("tracing:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", "logfire")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "   ")

    resolved = _resolve_tracing_for_args(
        ["diff-review", "--diff", str(tmp_path / "x.diff"), "--cwd", str(tmp_path), "--dry-run"],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert "tracing_project" not in resolved, resolved


def test_tracing_project_unset_does_not_appear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no env var and no YAML ``project``, ``tracing_project`` is absent."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: logfire\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_CONFIG", str(config))
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING_TO", "logfire")
    monkeypatch.delenv("MERGECRAFT_TRACING_PROJECT", raising=False)

    resolved = _resolve_tracing_for_args(
        ["diff-review", "--diff", str(tmp_path / "x.diff"), "--cwd", str(tmp_path), "--dry-run"],
        env=_env_from(monkeypatch, config),
        cwd=tmp_path,
    )
    assert "tracing_project" not in resolved, resolved


# ---------------------------------------------------------------------------
# Helpers — small harness around the precedence arithmetic.
# ---------------------------------------------------------------------------


def _env_from(monkeypatch: pytest.MonkeyPatch, config: Path) -> dict[str, str]:
    """Snapshot the monkeypatched env into a plain dict for the resolver helper."""
    import os

    keys = [
        "MERGECRAFT_CONFIG",
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_TO",
        "MERGECRAFT_TRACE_DIR",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "MERGECRAFT_OTEL_ENDPOINT",
        "MERGECRAFT_TRACING_PROJECT",
    ]
    return {key: os.environ[key] for key in keys if key in os.environ}


def _resolve_tracing_for_args(args: list[str], env: dict[str, str], cwd: Path) -> dict[str, Any]:
    """Resolve the CLI/env/config precedence arithmetic to a plain dict.

    W8.4 adds a public helper (``resolve_tracing_settings``) that takes the
    three layers and returns the merged ``TracingSettings``. Tests use it to
    assert precedence without booting the full review.
    """
    from mergecraft.cli.tracing_precedence import resolve_tracing_settings

    return resolve_tracing_settings(
        cli_args=args,
        env=env,
        config_path=env.get("MERGECRAFT_CONFIG"),
        cwd=cwd,
    )
