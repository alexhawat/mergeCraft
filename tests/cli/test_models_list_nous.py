"""RED tests for ``mergecraft models list`` rendering the Nous row (#57 / W1).

Wave plan: ``.ignorelocal/waves/issues-nous-deepseek-v4-flash-wave-plan.md``
W1 — test-creator. Pins the user-facing surface: once W2 adds the ``nous``
provider to ``PROVIDERS``, ``mergecraft models list`` must enumerate the
``nous/deepseek/deepseek-v4-flash`` row and flip its credentials marker
when ``NOUS_API_KEY`` is set.

The catalog itself is asserted in ``tests/agents/test_agent_resolve_nous.py``
(W1.1). This file is the CLI surface — the table the operator actually sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

NOUS_SLUG = "nous/deepseek/deepseek-v4-flash"
NOUS_API_KEY_ENV = "NOUS_API_KEY"
CUSTOM_PROVIDER_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"

_CLEAR_KEYS: tuple[str, ...] = (
    NOUS_API_KEY_ENV,
    CUSTOM_PROVIDER_API_KEY_ENV,
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CURSOR_API_KEY",
)


def _clear_provider_env(monkeypatch: MonkeyPatch) -> None:
    for key in _CLEAR_KEYS:
        monkeypatch.delenv(key, raising=False)


# ── W1.9 — model list renders the nous row with credentials column ───────────


@pytest.mark.xfail(
    reason="green after W2: nous provider in PROVIDERS",
    strict=False,
)
def test_mergecraft_models_list_renders_nous_row_without_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    """``mergecraft models list`` includes the nous row when ``NOUS_API_KEY`` is unset."""
    _clear_provider_env(monkeypatch)

    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert NOUS_SLUG in result.stdout


@pytest.mark.xfail(
    reason="green after W2: nous provider in PROVIDERS",
    strict=False,
)
def test_mergecraft_models_list_renders_nous_row_with_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    """``mergecraft models list`` flips credentials ``no`` → ``yes`` when ``NOUS_API_KEY`` is set."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(NOUS_API_KEY_ENV, "nous-test-key")

    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0, result.stdout + result.stderr
    # Locate the nous row in the table. Rich tables render rows as
    # ``slug provider display credentials`` space-separated. We assert only that
    # the row exists — the ``yes`` / ``no`` marker is a behavioural pin for
    # W2 and is checked structurally below.
    assert NOUS_SLUG in result.stdout
    # Find the row whose first token is the nous slug and assert credentials column.
    nous_row = next(
        (line for line in result.stdout.splitlines() if line.lstrip().startswith(NOUS_SLUG)),
        None,
    )
    assert nous_row is not None, f"no row found for {NOUS_SLUG!r}"
    tokens = nous_row.split()
    # Row format: ``slug provider display credentials`` — last token is credentials.
    assert tokens[-1] == "yes", (
        f"expected credentials column to be 'yes' with NOUS_API_KEY set, row was: {nous_row!r}"
    )


# ── structural / collection smoke (always green) ─────────────────────────────


def test_models_list_help() -> None:
    """``mergecraft models --help`` enumerates the ``list`` subcommand (collection smoke)."""
    result = runner.invoke(app, ["models", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
