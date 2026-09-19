"""Security vocabulary: stems and named classes, plus the deflation guard (RA1.2).

N20 has two halves (D6): the eight-pattern vocabulary misses whole classes, and
``\\bauth\\b`` only matches the literal token. This module pins the vocabulary
half through ``infer_category_from_message`` — not by asserting a pattern string
appears in ``SECURITY_MESSAGE_PATTERNS`` (that would pin today's list and fail
on the stem relaxation for no reason).
"""

from __future__ import annotations

import pytest

from tests.findings.support import make_finding

_AUTH_STEMS = ("auth", "authentication", "authorization", "unauthenticated", "authorize")

#: ``auth`` forms that name a security concern and must infer Security.
_SECURITY_AUTH_FORMS = (
    "auth",
    "authentication",
    "authenticate",
    "authorize",
    "authorization",
    "authorized",
    "authorizer",
    "authorizing",
)

#: ``unauth``-prefixed forms have no word boundary before ``auth``; the separate
#: ``unauth`` pattern covers them, and it must keep doing so.
_UNAUTH_FORMS = ("unauthenticated", "unauthorized")

#: Ordinary prose that merely begins with ``auth`` — the ``author`` word family.
_AUTHOR_PROSE_FORMS = (
    "author",
    "authors",
    "authoring",
    "authored",
    "authorship",
    "authoritative",
    "authority",
    "authorities",
)

#: Control text with no security or docs vocabulary. Its inferred category is
#: the non-security category the prose forms must land on (not pinned by name).
_AUTHOR_PROSE_CONTROL = "The section is out of date"

_NAMED_SECURITY_CLASSES = (
    "Remote code execution via unsafe eval",
    "RCE in the template renderer",
    "Unsafe deserialization of a session payload",
    "Pickle load of untrusted bytes",
    "Path traversal in the static file handler",
    "SSRF through a user-controlled callback URL",
    "CSRF token is not validated",
    "XXE expansion in the XML parser",
    "Privilege escalation via a misordered check",
    "Prototype pollution in the config merge",
    "Open redirect on the login callback",
    "Hardcoded key committed in the source",
)


def test_auth_stems_infer_security_category() -> None:
    """Every ``auth`` stem infers Security — not just the literal token."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    for stem in _AUTH_STEMS:
        message = f"The {stem} path is wrong"
        assert infer_category_from_message(message) == "Security & Privacy", (
            f"{stem!r} did not infer Security & Privacy"
        )


def test_named_security_classes_infer_security_category() -> None:
    """Named vulnerability classes the eight-pattern vocabulary misses."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    for message in _NAMED_SECURITY_CLASSES:
        assert infer_category_from_message(message) == "Security & Privacy", (
            f"{message!r} did not infer Security & Privacy"
        )


def test_genuine_style_nit_is_still_capped() -> None:
    """The deflation job survives the repair: a real style nit still caps."""
    from mergecraft.findings.severity_rubric import apply_severity_rubric

    finding = make_finding(
        category="Maintainability & Code Quality",
        severity="Critical",
        message="Prefer f-string over percent formatting",
        path="src/util.py",
        start_line=3,
        end_line=3,
    )

    normalized = apply_severity_rubric(finding, model_assigned_severity="Critical")

    assert normalized.severity not in {"Critical", "Major"}


@pytest.mark.parametrize("form", _SECURITY_AUTH_FORMS)
def test_security_auth_forms_infer_security_category(form: str) -> None:
    """Every security ``auth`` form infers Security — not just the literal token."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    assert infer_category_from_message(f"The {form} path is wrong") == "Security & Privacy", (
        f"{form!r} did not infer Security & Privacy"
    )


@pytest.mark.parametrize("form", _UNAUTH_FORMS)
def test_unauth_forms_infer_security_category(form: str) -> None:
    """``unauth`` forms are covered by their own pattern, not the relaxed stem."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    assert infer_category_from_message(f"The {form} path is wrong") == "Security & Privacy", (
        f"{form!r} did not infer Security & Privacy"
    )


@pytest.mark.parametrize("word", _AUTHOR_PROSE_FORMS)
def test_author_family_prose_does_not_infer_security_category(word: str) -> None:
    """The ``author`` word family is ordinary prose, never a security signal."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    inferred = infer_category_from_message(f"The {word} section is out of date")
    assert inferred != "Security & Privacy", f"{word!r} wrongly inferred Security & Privacy"
    assert inferred == infer_category_from_message(_AUTHOR_PROSE_CONTROL), (
        f"{word!r} did not match the non-security control category"
    )
