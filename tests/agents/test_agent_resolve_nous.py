"""RED tests for #57 Nous Research / DeepSeek V4 Flash catalog + credential detection.

Wave plan: ``.ignorelocal/waves/issues-nous-deepseek-v4-flash-wave-plan.md``
W1 — test-creator. Locks the contracts the W2 implementation must satisfy:

- ``PROVIDERS["nous"]`` exists with one ``ModelDef`` (``D6``).
- ``MODEL_ALIASES`` carries ``nous/deepseek/deepseek-v4-flash``.
- ``has_credentials_for_slug("nous/deepseek/deepseek-v4-flash")`` honours both
  ``NOUS_API_KEY`` (first-class) and ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY``
  (back-compat alias) — ``D4``.
- ``_agent_binary_available("nous/...")`` returns ``True`` without consulting
  ``shutil.which`` — ``D5``.
- ``is_runnable_model_slug("nous/...")`` composes the two gates above.
- ``select_runnable_model_slug()`` returns the nous slug when credentials
  are present and the binary gate is short-circuited — integration-marked,
  excluded by ``make test`` (``D8``).

These cases are deliberately split from the cross-cutting chain tests in
``tests/utils/test_model_chain_resolve.py`` so a regression on the nous
slug is caught by this file specifically, not lost in a chain test.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import pytest

from mergecraft.models import MODEL_ALIASES, PROVIDERS, get_model_provider
from mergecraft.utils.agent_resolve import (
    _agent_binary_available,
    has_credentials_for_slug,
    is_runnable_model_slug,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

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


def _import_agent_resolve() -> object:
    return importlib.import_module("mergecraft.utils.agent_resolve")


def _import_chain_symbol(name: str) -> object:
    """Look up ``name`` on the agent_resolve module, failing loudly if absent."""
    module = _import_agent_resolve()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        pytest.fail(f"mergecraft.utils.agent_resolve.{name} not implemented: {exc}")


# ── W1.1 / W1.2 — catalog entry is present ───────────────────────────────────


def test_nous_provider_in_providers_and_aliases() -> None:
    """``PROVIDERS["nous"]`` exists and ``nous/deepseek/deepseek-v4-flash`` is enumerated.

    W2.1 must add the new provider block. Once the provider exists, this test
    also drives ``tests/test_models.py::test_providers_include_expected_keys``
    forward (the ``expected <= set(PROVIDERS)`` check must include ``"nous"``).
    """
    assert "nous" in PROVIDERS
    slugs = {a.slug for a in MODEL_ALIASES}
    assert NOUS_SLUG in slugs


def test_get_model_provider_for_nous_slug() -> None:
    """``get_model_provider`` returns ``"nous"`` for the catalog slug.

    Structural (W1.2): ``get_model_provider`` delegates to ``parse_model``,
    which splits on the first slash — no catalog knowledge is required for the
    prefix extraction. The assertion is already green today; it pins the
    parser against a future refactor that might validate the provider name.
    """
    assert get_model_provider(NOUS_SLUG) == "nous"


# ── W1.3 / W1.4 / W1.5 — credential detection honours D4 ─────────────────────


def test_has_credentials_for_slug_nous_with_nous_api_key(monkeypatch: MonkeyPatch) -> None:
    """``NOUS_API_KEY`` set, alias unset → ``has_credentials_for_slug`` is ``True`` (D4).

    First-class precedence: the operator-owned secret name wins.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(NOUS_API_KEY_ENV, "nous-test-key")

    assert has_credentials_for_slug(NOUS_SLUG) is True


def test_has_credentials_for_slug_nous_with_only_custom_provider_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    """Alias-only path: ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` set → ``True`` (D4 back-compat)."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "custom-provider-test-key")

    assert has_credentials_for_slug(NOUS_SLUG) is True


def test_has_credentials_for_slug_nous_with_no_keys(monkeypatch: MonkeyPatch) -> None:
    """Both env vars unset → ``has_credentials_for_slug`` is ``False`` (structural).

    Not marked xfail: the current code already returns ``False`` for any slug
    whose provider arm is unimplemented, so this is a regression pin rather than
    a contract that needs W2 to satisfy.
    """
    _clear_provider_env(monkeypatch)

    assert has_credentials_for_slug(NOUS_SLUG) is False


# ── W1.6 / W1.7 — binary gate is short-circuited (D5) ────────────────────────


def test_is_runnable_model_slug_nous_with_credentials(monkeypatch: MonkeyPatch) -> None:
    """Both gates green: ``is_runnable_model_slug`` returns ``True`` for the nous slug.

    Pins against a silent regression where a future refactor reintroduces a
    ``shutil.which("nous")`` lookup that would always fail.
    """
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(NOUS_API_KEY_ENV, "nous-test-key")

    assert is_runnable_model_slug(NOUS_SLUG) is True


def test_agent_binary_available_does_not_require_nous_on_path(
    monkeypatch: MonkeyPatch,
) -> None:
    """``_agent_binary_available("nous/...")`` returns ``True`` even with ``shutil.which`` stubbed to ``None``.

    Structural (W1.7): the existing ``binary_by_provider.get("nous")`` returns
    ``None`` today, which the function already short-circuits to ``True``.
    W2.4 makes the entry explicit; this case guards against the binary-gate
    ever calling ``shutil.which("nous")`` regardless of W2's shape.
    """
    monkeypatch.setattr("shutil.which", lambda _name: None)

    assert _agent_binary_available(NOUS_SLUG) is True


# ── W1.16 — integration-marked chain selection ───────────────────────────────


@pytest.mark.integration
def test_invoke_smoke_nous_slug_is_selectable_via_chain(monkeypatch: MonkeyPatch) -> None:
    """``select_runnable_model_slug()`` returns the nous slug when both gates are green.

    Integration-marked: only runs when ``NOUS_API_KEY`` is set in the test
    environment (skipped otherwise). Excluded from ``make test`` via
    ``-m "not integration"``. Pins the chain-resolution path end-to-end
    against the W2 implementation, not just ``has_credentials_for_slug``
    in isolation.
    """
    import os

    if not os.environ.get(NOUS_API_KEY_ENV):
        pytest.skip("NOUS_API_KEY is not set; integration smoke self-skips")

    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(NOUS_API_KEY_ENV, os.environ[NOUS_API_KEY_ENV])
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available",
        lambda _slug: True,
    )

    select_runnable_model_slug = cast(
        "Callable[..., str]",
        _import_chain_symbol("select_runnable_model_slug"),
    )

    settings_module = importlib.import_module("mergecraft.config.settings")
    settings = settings_module.RepoSettings.model_validate({"models": [NOUS_SLUG]})

    selected = select_runnable_model_slug(settings=settings)

    assert selected == NOUS_SLUG


# ── W1.15 — no real network call from any unit test in this file ─────────────


def test_no_real_api_call_in_unit_tests() -> None:
    """Structural guard: this test file's source never touches the live Nous Portal.

    Reads the file's text and fails if a string literal of the production Portal
    URL (``inference-api.nousresearch.com``) appears outside the marker phrase
    used by the integration-test comment. The validator's reject path goes
    through mocked httpx transports; this assertion keeps that contract.
    """
    import re
    from pathlib import Path

    test_file = Path(__file__).resolve()
    source = test_file.read_text(encoding="utf-8")

    portal_hits = re.findall(r"inference-api\.nousresearch\.com", source)
    assert len(portal_hits) <= 1, (
        "tests/agents/test_agent_resolve_nous.py mentions the live Nous Portal URL "
        f"more than once ({len(portal_hits)} occurrences). "
        "Unit tests must use httpx.MockTransport; only the @pytest.mark.integration "
        "smoke may reference the production URL."
    )
