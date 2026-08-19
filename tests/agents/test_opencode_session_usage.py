"""#273 second ingress — cached-token accounting in the opencode HTTP session path.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-19-wave-plan.md``
(Batch D / W18b, inserted from W18's finding). Live anchor:
``agents/opencode.py:401-427``.

W18 fixed ``StreamSpanAccumulator.to_usage()``
(``agents/_stream_consumer.py``), which serves the CLI streaming drivers.
``_prompt_session_http`` — the HTTP session path that serves the Nous /
MiniMax passthrough — **re-implemented the same details-block scan inline**
and still did ``input_tokens = inp + cache_read``. OpenAI-style
``*_tokens_details.cached_tokens`` are already inside the reported input
count, so that path kept over-reporting prompt size by the whole cached
count. W18b closed it by importing and reusing ``_resolve_cache_read``
instead of re-deriving the scan, which is why the duplicated-rule bug class
that let #273 survive W18 here cannot recur.

Reusing the helper **changed one thing beyond the fix**: the inline scan
checked the details block *first* and consulted the Anthropic-native
``cache_read_input_tokens`` / ``cacheReadTokens`` fields only as a fallback,
whereas ``_resolve_cache_read`` reads the native fields first. That flips
which field wins on a payload carrying both shapes. W18b took native-first
deliberately (see
``test_both_cache_shapes_resolve_native_first_by_deliberate_choice``); this
suite pins the resulting contract in both directions so it stays a decision
rather than drifting back by accident.

``input_tokens``/``output_tokens`` also accept the short ``input`` /
``output`` aliases here, which the accumulator does not — the alias arms
stay pinned because the fix depends on ``_resolve_cache_read`` never
reading the token-count fields at all.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest

from mergecraft.agents.opencode import _prompt_session_http

_INPUT = 100
_CACHED = 40
_OUTPUT = 7

_OPENAI_CHAT_INFO: dict[str, Any] = {
    "input_tokens": _INPUT,
    "output_tokens": _OUTPUT,
    "prompt_tokens_details": {"cached_tokens": _CACHED},
}
_OPENAI_RESPONSES_INFO: dict[str, Any] = {
    "input_tokens": _INPUT,
    "output_tokens": _OUTPUT,
    "input_tokens_details": {"cached_tokens": _CACHED},
}
_ANTHROPIC_INFO: dict[str, Any] = {
    "input_tokens": _INPUT,
    "output_tokens": _OUTPUT,
    "cache_read_input_tokens": _CACHED,
}

_OPENAI_SHAPES = (
    pytest.param(_OPENAI_CHAT_INFO, id="prompt_tokens_details"),
    pytest.param(_OPENAI_RESPONSES_INFO, id="input_tokens_details"),
)

# ``_prompt_session_http`` reads usage from ``data["info"]`` or
# ``data["usage"]``; both keys are exercised so a fix cannot be scoped to one.
_USAGE_KEYS = ("info", "usage")


class _StubResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.status_code = 200
        self.content = b"{}"
        self.text = "{}"

    def json(self) -> dict[str, Any]:
        return self._body


class _StubClient:
    """Minimal stand-in for ``httpx.AsyncClient`` returning one canned body."""

    body: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> _StubResponse:
        return _StubResponse(type(self).body)


@pytest.fixture
def session_response(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a callable that pins the session response body for one call."""

    def _set(body: dict[str, Any]) -> None:
        client = type("_Client", (_StubClient,), {"body": body})
        monkeypatch.setattr(httpx, "AsyncClient", client)

    return _set


async def _usage_for(session_response: Any, info: dict[str, Any], *, usage_key: str) -> Any:
    session_response({"result": "reviewed", usage_key: info})
    result = await _prompt_session_http(
        base_url="http://127.0.0.1:9999",
        session_id="sess-1",
        text="review this",
        model=None,
    )
    assert result.success is True
    return result.usage


# ---------------------------------------------------------------------------
# The bug — OpenAI cached tokens are inclusive of the reported input count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("info", _OPENAI_SHAPES)
@pytest.mark.parametrize("usage_key", _USAGE_KEYS)
async def test_openai_cached_tokens_are_not_added_to_session_input_tokens(
    session_response: Any,
    info: dict[str, Any],
    usage_key: str,
) -> None:
    """#273 / D16 on the second ingress — the cached count is already in ``input``."""
    usage = await _usage_for(session_response, info, usage_key=usage_key)

    assert usage is not None
    assert usage.input_tokens == _INPUT
    assert usage.cache_read_tokens == _CACHED


@pytest.mark.parametrize("info", _OPENAI_SHAPES)
async def test_openai_cached_tokens_under_the_short_input_alias(
    session_response: Any,
    info: dict[str, Any],
) -> None:
    """The ``input`` / ``output`` aliases must not route around the fix.

    This path accepts ``info["input"]`` where the accumulator does not, so a
    fix scoped to the long field names would leave the alias inflated.
    """
    aliased = {
        key: value for key, value in info.items() if key not in {"input_tokens", "output_tokens"}
    }
    aliased["input"] = _INPUT
    aliased["output"] = _OUTPUT

    usage = await _usage_for(session_response, aliased, usage_key="info")

    assert usage is not None
    assert usage.input_tokens == _INPUT
    assert usage.cache_read_tokens == _CACHED


# ---------------------------------------------------------------------------
# The half that must NOT move — Anthropic counters are disjoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("usage_key", _USAGE_KEYS)
async def test_anthropic_native_cache_read_stays_additive(
    session_response: Any,
    usage_key: str,
) -> None:
    """Green guard: Anthropic's reported input excludes cache reads.

    Correct today and it must stay correct. This is the arm that fails if
    W18b "fixes" the double-count by deleting ``+ cache_read`` outright —
    which matters more here than on the accumulator, because this path
    checks the details block *first*, so the two provenances are resolved in
    the opposite order.
    """
    usage = await _usage_for(session_response, _ANTHROPIC_INFO, usage_key=usage_key)

    assert usage is not None
    assert usage.input_tokens == _INPUT + _CACHED
    assert usage.cache_read_tokens == _CACHED


@pytest.mark.parametrize("info", _OPENAI_SHAPES)
async def test_openai_cached_tokens_are_still_reported(
    session_response: Any,
    info: dict[str, Any],
) -> None:
    """Green guard: stop *adding* the cached count, keep *recording* it.

    Zeroing ``cache_read`` would satisfy the arms above while losing the
    ``cost.cache_read`` signal the llm.call span carries.
    """
    usage = await _usage_for(session_response, info, usage_key="info")

    assert usage is not None
    assert usage.cache_read_tokens == _CACHED
    assert usage.output_tokens == _OUTPUT


# ---------------------------------------------------------------------------
# The precedence W18b chose — deliberate, not incidental
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("details_key", ["prompt_tokens_details", "input_tokens_details"])
@pytest.mark.parametrize("usage_key", _USAGE_KEYS)
async def test_both_cache_shapes_resolve_native_first_by_deliberate_choice(
    session_response: Any,
    details_key: str,
    usage_key: str,
) -> None:
    """A payload carrying BOTH cache shapes resolves native-first and additive.

    **Do not "tidy" this to details-first.** Before W18b this path scanned the
    details block first and treated the native fields as a fallback, so a
    both-present payload was read as inclusive. W18b flipped it to native-first
    by reusing ``_resolve_cache_read`` from ``agents/_stream_consumer.py``, and
    that was an argued trade, not an oversight:

    - Keeping details-first would have needed either a second implementation of
      the rule or a precedence flag on a helper with exactly one such caller. A
      duplicated rule is precisely what let #273 survive W18 on this path, so
      reuse was the deliverable and the ordering change was its price.
    - The delta is confined to this both-present payload. No real provider emits
      both fields — they come from mutually exclusive APIs.
    - Native-first is the conservative direction for budget accounting: treating
      a genuinely disjoint count as inclusive would under-report prompt size and
      let a run overrun its bounds. Over-reporting merely ends a run early.

    ``_stream_consumer`` pins the same rule in
    ``tests/agents/test_stream_usage_cache.py::test_anthropic_native_field_wins_over_an_openai_details_block``.
    The two paths must stay locked to the *same* precedence — the wave that
    produced this test exists because they had diverged.
    """
    info = {
        "input_tokens": _INPUT,
        "output_tokens": _OUTPUT,
        "cache_read_input_tokens": _CACHED,
        # Deliberately a different value so the assertions below identify which
        # field won, not merely that some cached count survived.
        details_key: {"cached_tokens": 999},
    }

    usage = await _usage_for(session_response, info, usage_key=usage_key)

    assert usage is not None
    assert usage.cache_read_tokens == _CACHED
    assert usage.input_tokens == _INPUT + _CACHED


async def test_no_cache_fields_leaves_session_input_tokens_untouched(
    session_response: Any,
) -> None:
    """Green guard: a payload with neither cache shape is unaffected."""
    usage = await _usage_for(
        session_response,
        {"input_tokens": _INPUT, "output_tokens": _OUTPUT},
        usage_key="info",
    )

    assert usage is not None
    assert usage.input_tokens == _INPUT
    assert usage.cache_read_tokens is None


async def test_session_without_usage_reports_no_usage(session_response: Any) -> None:
    """Green guard: no token fields ⇒ ``usage is None``, not a zero-filled record."""
    session_response({"result": "reviewed"})

    result = await _prompt_session_http(
        base_url="http://127.0.0.1:9999",
        session_id="sess-1",
        text="review this",
        model=None,
    )

    assert result.success is True
    assert result.usage is None
