"""A structured tool payload must be redacted as a structure, not as text.

``redact_tool_payload`` serialised dicts and lists before redacting, which
threw away the only signal a deny-key match has. Once ``{"password": "x"}`` is
a string, the quoted key matches no text pattern and a short value clears no
entropy threshold, so the secret reached ``gen_ai.tool.output`` verbatim.
``redact_attrs`` in the same module already redacted structures first; this
path was the exception.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.redaction_structured import DENY_KEYS
from mergecraft.tracing.redaction import redact_tool_payload

_SHORT_SECRET = "hunter2"


@pytest.mark.parametrize("key", sorted(DENY_KEYS))
def test_every_deny_key_is_redacted_at_the_top_level(key: str) -> None:
    """Parametrised over the whole deny list, not a sample.

    The defect was a whole category escaping, so one representative key would
    have proved little and a new deny key added later must be covered by
    construction rather than by someone remembering to extend a literal list.
    """
    out = redact_tool_payload({key: _SHORT_SECRET})

    assert _SHORT_SECRET not in out, f"{key!r} leaked its value: {out}"


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("nested dict", {"outer": {"password": _SHORT_SECRET}}),
        ("list of dicts", [{"token": _SHORT_SECRET}]),
        ("dict of lists", {"items": [{"api_key": _SHORT_SECRET}]}),
        ("deeply nested", {"a": {"b": [{"c": {"secret": _SHORT_SECRET}}]}}),
    ],
)
def test_deny_keys_inside_containers_are_redacted(label: str, payload: Any) -> None:
    """A secret does not become safe by sitting one container deeper."""
    out = redact_tool_payload(payload)

    assert _SHORT_SECRET not in out, f"{label} leaked: {out}"


def test_a_short_low_entropy_secret_is_the_case_that_regressed() -> None:
    """Pin the exact reported payload.

    ``hunter2`` is deliberately short and low-entropy: it is invisible to both
    the text patterns and the entropy pass, so it only stays redacted while the
    key match survives. A future refactor that reintroduces serialise-then-scan
    passes every other test in this file and fails this one.
    """
    out = redact_tool_payload({"password": _SHORT_SECRET})

    assert "hunter2" not in out
    assert "password" in out, "the key should remain visible; only the value goes"


def test_benign_payloads_are_left_alone() -> None:
    """Guard the guard: redacting structures must not blank ordinary content."""
    assert redact_tool_payload({"q": "hello"}) == '{"q": "hello"}'
    assert redact_tool_payload(["a", "b"]) == '["a", "b"]'


def test_string_payloads_still_use_the_text_path() -> None:
    """Strings have no structure to walk; the pattern scan still applies."""
    out = redact_tool_payload("Bearer ghp_abcdefghijklmnopqrstuvwxyz1234")

    assert "ghp_abcdefghijklmnopqrstuvwxyz1234" not in out


def test_an_unserialisable_payload_is_still_redacted() -> None:
    """The ``json.dumps`` fallback must not bypass redaction.

    ``default=str`` covers most objects, so this pins the branch that does not:
    falling back to ``str()`` on the *redacted* structure rather than the raw
    one, which would have re-leaked what the walk just removed.
    """

    class Unserialisable:
        def __repr__(self) -> str:  # pragma: no cover - exercised via str()
            return "<obj>"

    out = redact_tool_payload({"password": _SHORT_SECRET, "obj": Unserialisable()})

    assert _SHORT_SECRET not in out
