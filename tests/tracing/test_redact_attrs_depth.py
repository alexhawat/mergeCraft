"""BR1.1 / BR2 — nested ``redact_attrs`` deny-key coverage (MCB-03)."""

from __future__ import annotations

import json

import pytest

_BASIC_AUTH = "Basic dXNlcjpwYXNzd29yZA=="
_NESTED_SECRET = "nested-canary-api-key-value-01"


@pytest.mark.parametrize(
    "attrs",
    [
        {"authorization": _NESTED_SECRET},
        {"wrapper": {"authorization": _NESTED_SECRET}},
        {"outer": {"inner": {"api_key": _NESTED_SECRET}}},
    ],
    ids=["depth-1", "depth-2", "depth-3"],
)
def test_deny_keys_apply_at_depth_1_2_3(attrs: dict[str, object]) -> None:
    """MCB-03: deny keys must redact at every nesting depth."""
    from mergecraft.tracing.redaction import redact_attrs

    redacted = redact_attrs(attrs)
    serialized = json.dumps(redacted, default=str)
    assert _NESTED_SECRET not in serialized


def test_deny_keys_apply_through_a_list_of_dicts() -> None:
    """MCB-03: list/tuple containers must not bypass deny-key checks."""
    from mergecraft.tracing.redaction import redact_attrs

    attrs = {
        "headers": [
            {"authorization": _NESTED_SECRET},
            {"cookie": "session=canary-cookie-value-01"},
        ]
    }
    redacted = redact_attrs(attrs)
    serialized = json.dumps(redacted, default=str)
    assert _NESTED_SECRET not in serialized
    assert "canary-cookie-value-01" not in serialized


def test_basic_auth_material_is_redacted() -> None:
    """MCB-03: Basic-auth blobs must not clear both pattern and entropy gates."""
    from mergecraft.tracing.redaction import redact_attrs

    redacted = redact_attrs({"authorization": _BASIC_AUTH})
    serialized = json.dumps(redacted, default=str)
    assert "dXNlcjpwYXNzd29yZA==" not in serialized
    assert _BASIC_AUTH not in serialized
