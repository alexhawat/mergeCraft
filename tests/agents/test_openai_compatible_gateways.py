"""RED tests for the shared custom-provider resolver (D7 / W3 / W1.4).

The ``mergecraft.agents.openai_compatible_gateways`` module is the single
shared helper both ``agents/opencode.py`` and ``agents/codex.py`` consume.
W3 lifts its signature to a multi-provider shape; these tests pin the
contract W3 must produce.

Operator-locked convention (W1 design decision, recorded in the wave plan
+ test-plan doc):

  - Indexed pairs: ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY_<N>`` and
    ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_<N>`` for ``N >= 1``.
  - Provider id: ``"provider_" + str(N)`` (deterministic, suffix-derived).
  - Discovery: enumerate every ``os.environ`` key matching
    ``MERGECRAFT_CUSTOM_PROVIDER_(API_KEY|BASE_URL)_\\d+``, pair by numeric
    suffix, require both halves per index. Gaps are preserved (no renumbering).
  - Singleton: ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` /
    ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL`` (PR #79 / D7) is a back-compat
    alias for a single ``default`` provider id; ignored when any indexed
    pair is present.

Wave plan: ``.ignorelocal/waves/issues-provider-routing-wave-plan.md``
(Batch B / W1). Cross-wave xfail markers use ``strict=False``.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

INDEXED_API_KEY_RE = re.compile(r"^MERGECRAFT_CUSTOM_PROVIDER_API_KEY_(\d+)$")
INDEXED_BASE_URL_RE = re.compile(r"^MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_(\d+)$")

PROVIDER_1_ID = "provider_1"
PROVIDER_2_ID = "provider_2"
PROVIDER_3_ID = "provider_3"
DEFAULT_PROVIDER_ID = "default"


def _load_gateways_module() -> object:
    try:
        return importlib.import_module("mergecraft.agents.openai_compatible_gateways")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.openai_compatible_gateways not importable: {exc}")


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", raising=False)
    for n in range(1, 8):
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}", raising=False)
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}", raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)


# -- W1.4: shared helper returns a multi-provider shape --------------------


@pytest.mark.xfail(
    reason="green after W3: shared helper exposes a multi-provider resolver "
    "(dict/sequence of ProviderRecord keyed by provider id)",
    strict=False,
)
def test_shared_helper_exposes_multi_provider_resolver() -> None:
    """The shared module exposes a callable returning a multi-provider shape.

    Today the module exposes ``resolve_gateway_endpoint(model) -> tuple | None``
    (a singleton). W3 must add a multi-provider resolver. Acceptable shapes:
    ``dict[str, ProviderRecord]`` or a sequence of records; the test asserts
    either, by name, is importable from the module.
    """
    gateways = _load_gateways_module()

    # Acceptable function names for the multi-provider resolver.
    candidate_names = (
        "resolve_gateway_endpoints",
        "list_custom_providers",
        "resolve_all_gateway_endpoints",
        "iter_gateway_endpoints",
        "all_gateway_endpoints",
    )
    found = next(
        (name for name in candidate_names if hasattr(gateways, name)),
        None,
    )
    assert found is not None, (
        f"shared helper must expose a multi-provider resolver; "
        f"expected one of {candidate_names}, none found"
    )


@pytest.mark.xfail(
    reason="green after W3: multi-provider resolver returns dict keyed by provider id",
    strict=False,
)
def test_shared_multi_provider_resolver_handles_indexed_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``_1`` and ``_2`` set, the resolver returns a dict containing
    ``provider_1`` and ``provider_2`` keys (no silent renumbering).
    """
    gateways = _load_gateways_module()
    resolver = _resolve_multi_provider_callable(gateways)
    assert resolver is not None, "shared helper must expose a multi-provider resolver"

    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1", "https://provider-1.example.test/v1"
    )
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", "key-1")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_2", "https://provider-2.example.test/v1"
    )
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_2", "key-2")

    result = resolver()
    as_dict = _coerce_to_dict(result)
    assert PROVIDER_1_ID in as_dict
    assert PROVIDER_2_ID in as_dict


@pytest.mark.xfail(
    reason="green after W3: multi-provider resolver preserves gaps (no renumbering)",
    strict=False,
)
def test_shared_multi_provider_resolver_preserves_index_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_1`` + ``_3`` set, ``_2`` absent → providers 1 and 3 present, 2 absent."""
    gateways = _load_gateways_module()
    resolver = _resolve_multi_provider_callable(gateways)
    assert resolver is not None

    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1", "https://provider-1.example.test/v1"
    )
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", "key-1")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_3", "https://provider-3.example.test/v1"
    )
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_3", "key-3")

    result = resolver()
    as_dict = _coerce_to_dict(result)
    assert PROVIDER_1_ID in as_dict
    assert PROVIDER_3_ID in as_dict
    assert PROVIDER_2_ID not in as_dict


@pytest.mark.xfail(
    reason="green after W3: partial indexed pair (only one half set) is dropped",
    strict=False,
)
def test_shared_multi_provider_resolver_drops_partial_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``_1`` API key set (no base URL) → ``provider_1`` absent."""
    gateways = _load_gateways_module()
    resolver = _resolve_multi_provider_callable(gateways)
    assert resolver is not None

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", "key-1")
    # Base URL not set.

    result = resolver()
    as_dict = _coerce_to_dict(result)
    assert PROVIDER_1_ID not in as_dict


@pytest.mark.xfail(
    reason="green after W3: singleton maps to 'default' when no indexed pair set",
    strict=False,
)
def test_shared_multi_provider_resolver_singleton_maps_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Singleton alone → a single ``default`` provider id."""
    gateways = _load_gateways_module()
    resolver = _resolve_multi_provider_callable(gateways)
    assert resolver is not None

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://default.example.test/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "default-key")

    result = resolver()
    as_dict = _coerce_to_dict(result)
    assert DEFAULT_PROVIDER_ID in as_dict
    assert PROVIDER_1_ID not in as_dict


@pytest.mark.xfail(
    reason="green after W3: when any indexed pair is set, the singleton is ignored",
    strict=False,
)
def test_shared_multi_provider_resolver_indexed_overrides_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexed + singleton → only indexed entries; singleton ignored."""
    gateways = _load_gateways_module()
    resolver = _resolve_multi_provider_callable(gateways)
    assert resolver is not None

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://default.example.test/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "default-key")
    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1", "https://provider-1.example.test/v1"
    )
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", "key-1")

    result = resolver()
    as_dict = _coerce_to_dict(result)
    assert PROVIDER_1_ID in as_dict
    assert DEFAULT_PROVIDER_ID not in as_dict


# -- Thermos Blocker #1: scoped credential gate -----------------------------
#
# ``has_gateway_credentials`` must only report credentials for a named preset
# when THAT preset's own env vars are set. An unrelated indexed custom-provider
# pair (``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>``) maps to a generic
# ``provider_<N>`` id, NOT to the named ``minimax`` / ``nous`` / ``tokenhub``
# presets — so it must not make ``has_gateway_credentials`` return True for them.
# Regression: a Batch C addition let ``resolve_gateway_endpoints()`` short-circuit
# the gate, causing every preset to false-positive.


def test_indexed_pair_does_not_grant_minimax_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated indexed pair must NOT make ``minimax`` report credentials."""
    from mergecraft.agents.openai_compatible_gateways import has_gateway_credentials

    monkeypatch.setenv(
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1", "https://provider-1.example.test/v1"
    )
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1", "key-1")

    assert has_gateway_credentials("minimax") is False


def test_singleton_still_grants_minimax_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The singleton custom-provider pair still honours ``minimax`` (back-compat)."""
    from mergecraft.agents.openai_compatible_gateways import has_gateway_credentials

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "https://default.example.test/v1")
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "default-key")

    assert has_gateway_credentials("minimax") is True


def test_nous_back_compat_alias_still_grants_nous_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``NOUS_API_KEY`` still grants ``nous`` credentials (D4 back-compat alias)."""
    from mergecraft.agents.openai_compatible_gateways import has_gateway_credentials

    monkeypatch.setenv("NOUS_API_KEY", "nous-key")

    assert has_gateway_credentials("nous") is True


# -- helpers -----------------------------------------------------------------


def _resolve_multi_provider_callable(module: object):
    for name in (
        "resolve_gateway_endpoints",
        "list_custom_providers",
        "resolve_all_gateway_endpoints",
        "iter_gateway_endpoints",
        "all_gateway_endpoints",
    ):
        if hasattr(module, name):
            return getattr(module, name)
    return None


def _coerce_to_dict(result: object) -> dict[str, object]:
    """Normalise either a ``dict`` or a sequence of records to a dict keyed by id."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "__iter__"):
        out: dict[str, object] = {}
        for item in result:
            if isinstance(item, dict):
                pid = item.get("provider_id") or item.get("id")
                if isinstance(pid, str):
                    out[pid] = item
            else:
                pid = getattr(item, "provider_id", None) or getattr(item, "id", None)
                if isinstance(pid, str):
                    out[pid] = item
        return out
    pytest.fail(f"shared helper returned unrecognised shape: {type(result).__name__}")


# -- W1.4 (structural): both harnesses import the shared helper -------------
#
# Today the opencode harness imports ``resolve_gateway_endpoint`` from
# ``openai_compatible_gateways``; codex does not yet import from there
# (W3.1 will rewire codex). The structural assertion pin down below is the
# W3 contract; today codex does NOT import, so this test is xfailed.


def test_both_harnesses_consume_the_shared_helper() -> None:
    """Both ``opencode.py`` and ``codex.py`` import a function from
    ``openai_compatible_gateways`` — the shared helper backs both harnesses.

    The harness modules are wrapped by the ``agent()`` decorator (an
    ``AgentImpl``), so ``inspect.getsource`` does not work directly. The
    test reads the source files on disk and checks the helper module name
    appears in the imports.
    """
    from pathlib import Path

    repo_src = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "agents"
    opencode_src = (repo_src / "opencode.py").read_text(encoding="utf-8")
    codex_src = (repo_src / "codex.py").read_text(encoding="utf-8")
    assert "openai_compatible_gateways" in opencode_src
    assert "openai_compatible_gateways" in codex_src


# -- W1.4 (structural): ProviderRecord exposes fields for log redaction -----
#
# The helper's record must carry the env-var names that sourced it so the
# harness can pass them to loguru's redactor without ever emitting the
# resolved value. W3 lands a typed record (e.g. ``ProviderRecord``) with
# those fields; today no such type exists, so the import is xfailed.


@pytest.mark.xfail(
    reason="green after W3: shared helper exposes a typed ProviderRecord with env-var provenance",
    strict=False,
)
def test_provider_record_carries_env_var_provenance() -> None:
    """A typed ``ProviderRecord`` (or equivalent) must carry the env-var
    names that sourced ``base_url`` and ``api_key`` — required for log
    redaction (convention 7).
    """
    gateways = _load_gateways_module()
    record_type = getattr(gateways, "ProviderRecord", None)
    assert record_type is not None, (
        "shared helper must expose a typed ProviderRecord with env-var provenance"
    )

    fields = getattr(record_type, "__dataclass_fields__", None) or getattr(
        record_type, "model_fields", None
    )
    assert fields is not None, "ProviderRecord must be a dataclass or pydantic model"
    names = set(fields.keys())
    for required in ("provider_id", "base_url", "api_key", "base_url_env", "api_key_env"):
        assert required in names, f"ProviderRecord must carry field {required!r}"


# Avoid unused-import warning when TYPE_CHECKING is collapsed.
_ = Path
_ = INDEXED_API_KEY_RE
_ = INDEXED_BASE_URL_RE
