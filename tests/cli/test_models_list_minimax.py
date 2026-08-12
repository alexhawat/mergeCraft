"""RED tests for ``mergecraft models list`` rendering the MiniMax row (#34 / W5).

Wave plan: ``.ignorelocal/waves/issues-provider-routing-wave-plan.md``
(Batch C / W5). Pins the user-facing surface: once W6 adds the ``minimax``
catalog entry (D10 / option ii — routed through the W3 custom-provider
helper, NOT a bespoke ``mmx-cli`` harness), ``mergecraft models list``
must enumerate the ``minimax/MiniMax-M3`` row and flip its credentials
marker when the operator has the custom-provider env vars configured.

The catalog itself is asserted in
``tests/agents/test_minimax_routing.py`` (W5.1, W5.6). This file is the
CLI surface — the table the operator actually sees — modelled on
``tests/cli/test_models_list_nous.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

MINIMAX_SLUG = "minimax/MiniMax-M3"
SINGLETON_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
SINGLETON_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"

_CLEAR_KEYS: tuple[str, ...] = (
    SINGLETON_BASE_URL_ENV,
    SINGLETON_API_KEY_ENV,
    # Wipe a generous range of indexed suffixes.
    *(f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}" for n in range(1, 8)),
    *(f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}" for n in range(1, 8)),
    "NOUS_API_KEY",
    "TOKENHUB_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CURSOR_API_KEY",
)


def _clear_provider_env(monkeypatch: MonkeyPatch) -> None:
    for key in _CLEAR_KEYS:
        monkeypatch.delenv(key, raising=False)


# ── W5.4 — model list renders the minimax row with credentials column ──────


@pytest.mark.xfail(
    reason=(
        "green after W6: the minimax/MiniMax-M3 catalog entry must be enumerated "
        "by ``mergecraft models list`` even when no MERGECRAFT_CUSTOM_PROVIDER_* "
        "env var is set (D10 / option ii — MiniMax routed via the W3 helper)"
    ),
    strict=False,
)
def test_mergecraft_models_list_renders_minimax_row_without_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    """``mergecraft models list`` includes the minimax row when no
    ``MERGECRAFT_CUSTOM_PROVIDER_*`` env var is set.

    The row's credentials column flips to ``yes`` when the env vars are
    set (parametric case below); this case pins the un-set default.
    """
    _clear_provider_env(monkeypatch)

    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert MINIMAX_SLUG in result.stdout, (
        f"expected {MINIMAX_SLUG!r} in mergecraft models list output; got: {result.stdout!r}"
    )


@pytest.mark.xfail(
    reason=(
        "green after W6: the minimax/MiniMax-M3 catalog entry must be enumerated "
        "by ``mergecraft models list`` (D10 / option ii — MiniMax routed via the "
        "W3 custom-provider helper)"
    ),
    strict=False,
)
def test_mergecraft_models_list_renders_minimax_row_with_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    """``mergecraft models list`` flips the credentials column to ``yes``
    when ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` is set (D10 / option ii:
    MiniMax routes through the W3 helper).

    Locates the minimax row by its first token; the row format is
    ``slug provider display credentials`` (space-separated), with the
    credentials column as the trailing token. The ``yes`` / ``no``
    marker is the W6 behavioural pin.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(SINGLETON_API_KEY_ENV, "minimax-test-key")

    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert MINIMAX_SLUG in result.stdout

    minimax_row = next(
        (line for line in result.stdout.splitlines() if line.lstrip().startswith(MINIMAX_SLUG)),
        None,
    )
    assert minimax_row is not None, f"no row found for {MINIMAX_SLUG!r}"
    tokens = minimax_row.split()
    # Row format: ``slug provider display credentials`` — last token is credentials.
    assert tokens[-1] == "yes", (
        f"expected credentials column to be 'yes' with MERGECRAFT_CUSTOM_PROVIDER_API_KEY set, "
        f"row was: {minimax_row!r}"
    )


@pytest.mark.xfail(
    reason=(
        "green after W6: even when the credentials column flips to ``yes``, the "
        "rendered table must not leak the api key value into stdout (convention 7)"
    ),
    strict=False,
)
def test_mergecraft_models_list_minimax_row_does_not_leak_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    """Convention 7: the resolved api key value never appears in the
    rendered table — even when the credentials column flips to ``yes``.

    Pins against a regression where ``mergecraft models list`` would
    print the raw env var value alongside the row.
    """
    _clear_provider_env(monkeypatch)
    sentinel = "sk-minimax-table-SENTINEL-LEAK-CHECK-0001"
    monkeypatch.setenv(SINGLETON_API_KEY_ENV, sentinel)

    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert sentinel not in result.stdout, (
        "mergecraft models list leaked the api key value into stdout"
    )


# ── structural / collection smoke (always green) ─────────────────────────────


def test_models_list_help() -> None:
    """``mergecraft models --help`` enumerates the ``list`` subcommand (collection smoke)."""
    result = runner.invoke(app, ["models", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
