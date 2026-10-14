"""No ``tests/scm/`` fixture patches httpx for the whole process.

An autouse conftest fixture installed a latin-1 header normaliser on
``httpx._models`` and never restored it, so every later test in the same worker
saw the mutated library. The only tests that needed it pushed non-ASCII header
bytes through ``TestClient`` on the removed webhook route, so the patch
machinery — ``tests/scm/_httpx_compat.py`` and its fixture — is deleted rather
than scoped.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mergecraft.scm.webhooks import sign_webhook_payload, verify_webhook_signature

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPAT = _REPO_ROOT / "tests" / "scm" / "_httpx_compat.py"
_CONFTEST = _REPO_ROOT / "tests" / "scm" / "conftest.py"

_SECRET = "scoped-httpx-patch-secret"
_BODY = b'{"action":"opened"}'
_NON_ASCII_BYTE = bytes([0x80]).decode("latin-1")


def test_httpx_models_carries_no_process_wide_patch_marker() -> None:
    """After any ``tests/scm/`` test has run, httpx is left as the library shipped it."""
    assert not getattr(httpx._models, "_mergecraft_latin1_patched", False), (
        "a process-wide latin-1 patch leaked out of tests/scm"
    )
    # Surviving surface: signature verification needs no process-wide patch.
    signed = sign_webhook_payload("github", body=_BODY, secret=_SECRET)
    verify_webhook_signature("github", headers=signed, body=_BODY, secret=_SECRET)
    with pytest.raises(PermissionError, match=r"signature|hmac|unauthor"):
        verify_webhook_signature(
            "github",
            headers={"X-Hub-Signature-256": "sha256=deadbeef"},
            body=_BODY,
            secret=_SECRET,
        )


def test_the_process_wide_patch_machinery_is_gone() -> None:
    """The compat module and its conftest wiring are deleted, not merely scoped."""
    assert not _COMPAT.is_file(), "tests/scm/_httpx_compat.py should have been deleted"
    conftest_source = _CONFTEST.read_text(encoding="utf-8")
    assert "install_httpx_latin1_header_values" not in conftest_source
    assert "_mergecraft_latin1_patched" not in conftest_source
    # Surviving surface: non-ASCII headers still fail closed with plain dicts.
    headers = sign_webhook_payload("github", body=_BODY, secret=_SECRET)
    headers["X-Hub-Signature-256"] = f"sha256={_NON_ASCII_BYTE}"
    with pytest.raises(PermissionError):
        verify_webhook_signature("github", headers=headers, body=_BODY, secret=_SECRET)
