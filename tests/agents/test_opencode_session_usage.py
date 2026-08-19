"""#273 second ingress — cached-token accounting in the opencode HTTP session path.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-19-wave-plan.md``
(Batch D / W18b, inserted from W18's finding). Live anchor:
``agents/opencode.py:401-427``.

W18 fixed ``StreamSpanAccumulator.to_usage()``
(``agents/_stream_consumer.py``), which serves the CLI streaming drivers.
``_prompt_session_http`` — the HTTP session path that serves the Nous /
MiniMax passthrough — **re-implements the same details-block scan inline**
and still does ``input_tokens = inp + cache_read``. OpenAI-style
``*_tokens_details.cached_tokens`` are already inside the reported input
count, so that path keeps over-reporting prompt size by the whole cached
count. #273's success criterion is only half met while it stands.

Two things make this path a different shape from ``_resolve_cache_read``,
not a copy of it:

- **Precedence is inverted.** The inline scan checks the details block
  *first* and falls back to the Anthropic-native ``cache_read_input_tokens``
  / ``cacheReadTokens`` fields only when no details block matched;
  ``_resolve_cache_read`` consults the native fields first. A fix that
  reuses the shared helper therefore also flips which field wins on a
  payload carrying both. No arm below pins that ambiguous payload — the
  same call W14 made for the mixed-stream case — but the native-only arm
  **is** pinned green so a fix cannot buy the OpenAI arms by dropping the
  disjoint Anthropic addition.
- ``input_tokens``/``output_tokens`` also accept the short ``input`` /
  ``output`` aliases here, which the accumulator does not.
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


@pytest.mark.xfail(
    reason="green after W18b: opencode HTTP session cache accounting",
    strict=False,
)
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


@pytest.mark.xfail(
    reason="green after W18b: opencode HTTP session cache accounting",
    strict=False,
)
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
