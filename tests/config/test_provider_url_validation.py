"""``validate_http_url`` hardening — PR #498 review (workflow YAML injection).

A stored provider URL is written verbatim into the consumer workflow YAML by
``cli/workflow_wf_yaml`` and ``cli/tracing_logfire_wf_yaml``. ``str.strip()``
only clears the ends, so an interior newline used to survive validation and
open a new key or step in the emitted workflow.
"""

from __future__ import annotations

import pytest

from mergecraft.config.provider_registry import validate_http_url

_INJECTION_URL = "https://gateway.example.invalid/v1\nMERGECRAFT_INJECTED: yes"


@pytest.mark.parametrize(
    "url",
    [
        _INJECTION_URL,
        "https://gateway.example.invalid/v1\r\nrun: echo pwned",
        "https://gateway.example.invalid/v1\ttab",
        "https://gateway.example.invalid/v1 space",
        "https://gateway.example.invalid/v1\x00null",
        "https://gateway.example.invalid/v1\x7fdel",
    ],
)
def test_control_characters_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="whitespace or control characters"):
        validate_http_url(url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://ok.example/v1", "https://ok.example/v1"),
        ("  https://ok.example/v1  ", "https://ok.example/v1"),
        ("\nhttps://ok.example/v1\n", "https://ok.example/v1"),
        ("http://ok.example:8080/v1?a=b#c", "http://ok.example:8080/v1?a=b#c"),
    ],
)
def test_surrounding_whitespace_still_strips(raw: str, expected: str) -> None:
    assert validate_http_url(raw) == expected


@pytest.mark.parametrize("url", ["ftp://ok.example/v1", "https://", "not-a-url", ""])
def test_non_http_urls_still_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="absolute http"):
        validate_http_url(url)
