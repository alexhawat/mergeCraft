"""No ``tests/scm/`` fixture patches httpx for the whole process.

An autouse conftest fixture installed a latin-1 header normaliser on
``httpx._models`` and never restored it, so every later test in the same worker
saw the mutated library. The patch is either scoped to the tests that need it
through ``monkeypatch`` or deleted with ``tests/scm/_httpx_compat.py``.
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


def test_the_patch_is_monkeypatch_scoped_or_deleted() -> None:
    """When the compat module survives, its applying fixture is non-autouse and restores via monkeypatch."""
    if not _COMPAT.is_file():
        return  # deleted with the tests that needed it
    source = _CONFTEST.read_text(encoding="utf-8")
    call = source.find("install_httpx_latin1_header_values(")
    assert call != -1, "the compat module exists but the conftest never applies it"
    decorator = source.rfind("@pytest.fixture", 0, call)
    assert decorator != -1, "the patch is applied outside a pytest fixture"
    fixture_block = source[decorator:call]
    decorator_line = fixture_block.splitlines()[0]
    assert "autouse=True" not in decorator_line, decorator_line
    assert "monkeypatch" in fixture_block, fixture_block
