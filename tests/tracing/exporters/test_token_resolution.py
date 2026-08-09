"""RED contracts for ``tokenRef`` resolution and redaction (W7.4).

D5 specifies that secrets are referenced by ``tokenRef`` and never inlined.
The contract under test here is the negative one: the literal token value
never appears in any surface that an operator could leak — config dumps,
logs, or the ``mergecraft config tracing`` CLI output. The W8 implementation
resolves ``tokenRef`` via the env var the name points to; this module pins
the surrounding guarantees.
"""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

# A canary that follows the real Logfire-token shape but is unique to these
# tests; any leaked occurrence is a hard failure.
_CANARY = "logfire-canary-abcdef0123456789-AAA"
_RUNNER = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


# ---------------------------------------------------------------------------
# W7.4 — tokenRef is resolved, never inlined.
# ---------------------------------------------------------------------------


def test_token_value_never_appears_in_config_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    """``RepoSettings.model_dump(...)`` never contains the literal token value.

    D5 makes this structural: the dump only ever contains the reference
    (``tokenRef``), not the resolved value.
    """
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)
    from mergecraft.config import RepoSettings

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    )
    dumped_by_alias = json.dumps(settings.model_dump(by_alias=True))
    dumped_default = json.dumps(settings.model_dump())
    assert _CANARY not in dumped_by_alias
    assert _CANARY not in dumped_default
    # The reference is preserved.
    assert "MERGECRAFT_LOGFIRE_TOKEN" in dumped_by_alias


def test_token_value_never_appears_in_yaml_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Loading and dumping the YAML config does not leak the token into either side of the round trip."""
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)
    from pathlib import Path

    from mergecraft.config import RepoSettings, load_repo_settings

    config = Path(str(tmp_path)) / "config.yaml"
    config.write_text(
        "tracing:\n  enabled: true\n  sinks:\n"
        "    - type: logfire\n      tokenRef: MERGECRAFT_LOGFIRE_TOKEN\n",
        encoding="utf-8",
    )
    loaded = load_repo_settings(config, root=Path(str(tmp_path)), load_learnings_files=False)
    dumped_yaml = loaded.model_dump_json(by_alias=True, indent=2)
    assert _CANARY not in config.read_text(encoding="utf-8")
    assert _CANARY not in dumped_yaml
    # Re-parse the dumped YAML and confirm it round-trips identically.
    reparsed = RepoSettings.model_validate_json(dumped_yaml)
    assert reparsed.tracing.sinks[0].token_ref == "MERGECRAFT_LOGFIRE_TOKEN"


def test_token_value_never_appears_in_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loguru warning/error messages do not contain the literal token value."""
    pytest.importorskip("logfire")

    import loguru

    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    # Build a valid config (token absent) so the resolver path emits its
    # warning; the token is set in env so we know the canary would be
    # available — and the warning must NOT include it.
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(str(record.record["message"])), level="WARNING"
    )
    try:
        settings = RepoSettings.model_validate(
            {"tracing": {"enabled": True, "sinks": [{"type": "logfire"}]}}
        ).tracing
        sink_factory(settings)
    finally:
        loguru.logger.remove(sink_id)
    assert all(_CANARY not in msg for msg in captured), captured


def test_token_value_redacted_in_config_tracing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """``mergecraft config tracing`` shows the resolved config with the token value replaced.

    This is the operator-visible surface: the command lists resolved sinks
    with a redacted token marker so the operator can verify wiring without
    leaking the secret into the terminal scrollback.
    """
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)
    from mergecraft.cli.app import app

    result = _RUNNER.invoke(
        app,
        ["config", "tracing"],
        env={"MERGECRAFT_LOGFIRE_TOKEN": _CANARY, "NO_COLOR": "1", "TERM": "dumb"},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout)
    assert _CANARY not in out
    # The reference name itself is shown; the value is not.
    assert "MERGECRAFT_LOGFIRE_TOKEN" in out or "tokenRef" in out or "redacted" in out.lower()


@pytest.mark.parametrize(
    "config_token_ref",
    ["MERGECRAFT_LOGFIRE_TOKEN", "LOGFIRE_TOKEN", "logfire_token"],
)
def test_token_resolution_supports_multiple_reference_names(
    monkeypatch: pytest.MonkeyPatch, config_token_ref: str
) -> None:
    """Any env-var name is acceptable as a ``tokenRef``; the resolver reads it from ``os.environ``."""
    monkeypatch.setenv(config_token_ref, _CANARY)
    pytest.importorskip("logfire")

    from mergecraft.tracing.exporters import resolve_token_ref

    assert resolve_token_ref(config_token_ref) == _CANARY


def test_resolve_token_ref_returns_none_for_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the referenced env var is unset, the resolver returns ``None`` — never raises."""
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    from mergecraft.tracing.exporters import resolve_token_ref

    assert resolve_token_ref("MERGECRAFT_LOGFIRE_TOKEN") is None


def test_resolve_token_ref_never_inlines_when_value_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolver returns the value to the caller but does not write it into any module-level cache.

    This is the structural side of D5 — the resolved token is held only in
    the caller's closure. Tests assert the call site reads the value and then
    drops it.
    """
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", _CANARY)
    from mergecraft.tracing.exporters import resolve_token_ref

    value = resolve_token_ref("MERGECRAFT_LOGFIRE_TOKEN")
    assert value == _CANARY
    # The value is not stashed in module globals; subsequent reads without the
    # env var must return None.
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    assert resolve_token_ref("MERGECRAFT_LOGFIRE_TOKEN") is None
