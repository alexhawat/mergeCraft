"""W14 / W16 — egress, SSRF, vuln gates, threat model (#362).

Out of scope: MCP authentication (#345/#346); review-only boundary (#350);
adversarial corpora (#363). Plan W16 also: no secrets in public comments.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import REPO_ROOT
from tests.support.cc_batch import decide_approval_defining_files, require_callable
from tests.support.cd_batch import (
    EGRESS_MODULE,
    PUBLIC_COMMENT_MODULE,
    d10_root_callback_owns_globals,
    green_after,
    module_exists,
    require_module,
)
from tests.support.dead_package_wiring import SRC_ROOT

_W16 = green_after(
    "W16",
    "egress, SSRF, vuln gates, threat model; no secrets in public comments (#362)",
)

_SSRF_URLS = [
    "http://127.0.0.1/latest/meta-data/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "file:///etc/passwd",
    "http://localhost:1/",
]


def test_egress_and_ssrf_module_does_not_exist_yet() -> None:
    """W14 current state — no network-boundary control module."""
    assert module_exists(EGRESS_MODULE) is False
    security_dir = SRC_ROOT / "security"
    if security_dir.is_dir():
        assert not list(security_dir.glob("*egress*"))
        assert not list(security_dir.glob("*ssrf*"))


def test_w16_does_not_touch_mcp_auth_or_a_second_approval_path() -> None:
    """#362 out of scope + D14 — MCP auth and ``decide_approval`` stay put."""
    d10_root_callback_owns_globals()
    assert decide_approval_defining_files() == ["agents/gates.py"]
    mcp_dir = SRC_ROOT / "mcp"
    auth_hits = [path.name for path in mcp_dir.glob("*auth*") if "oauth" not in path.name.lower()]
    assert "bearer.py" not in auth_hits


def test_make_security_target_already_exists() -> None:
    """#362 — container/image gates must be distinct from the shipped ``make security``."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "security:" in makefile or "\nsecurity :" in makefile


@_W16
def test_network_egress_controls_deny_unlisted_hosts() -> None:
    """Happy: egress allow-list denies an arbitrary host when deployment permits."""
    module = require_module(EGRESS_MODULE)
    allow = require_callable(module, "allow_egress")
    assert allow("api.github.com") is True
    denied = allow("evil.example")
    assert denied is False


@_W16
@pytest.mark.parametrize("url", _SSRF_URLS)
def test_ssrf_protections_block_link_local_and_metadata_urls(url: str) -> None:
    """Error: external retrieval refuses SSRF targets (type + message)."""
    module = require_module(EGRESS_MODULE)
    check = require_callable(module, "guard_external_url")
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError),
        match=r"ssrf|blocked|link-local|metadata|loopback|file:",
    ):
        check(url)


@_W16
def test_dependency_vulnerability_gate_is_invocable() -> None:
    """Happy: a dependency vuln gate exists as a named callable."""
    module = require_module(EGRESS_MODULE)
    gate = require_callable(module, "dependency_vulnerability_gate")
    report = gate()
    passed = getattr(report, "passed", None)
    if passed is None:
        passed = report.get("passed")
    assert passed is True or passed is False


@_W16
def test_container_image_vulnerability_gate_is_distinct_from_make_security() -> None:
    """Happy: image scanning is not an alias of ``make security``."""
    module = require_module(EGRESS_MODULE)
    gate = require_callable(module, "container_image_vulnerability_gate")
    report = gate()
    name = getattr(report, "name", None) or (
        report.get("name") if isinstance(report, dict) else None
    )
    command = str(report)
    assert "make security" not in command
    if name is not None:
        assert name != "make security"


@_W16
def test_threat_model_document_is_tied_to_executable_tests() -> None:
    """Happy: threat-model doc exists under ``docs/`` and names this test file."""
    doc = REPO_ROOT / "docs" / "THREAT-MODEL.md"
    assert doc.is_file(), "expected docs/THREAT-MODEL.md"
    text = doc.read_text(encoding="utf-8")
    assert "ssrf" in text.casefold() or "egress" in text.casefold()
    assert "test_cd_egress" in text or "tests/security/test_cd_egress.py" in text
    assert "independent security review" in text.casefold()


@_W16
def test_public_comments_never_include_secret_material() -> None:
    """Error: publication redacts tokens before they hit a public comment."""
    module = require_module(PUBLIC_COMMENT_MODULE)
    redact = require_callable(module, "redact_secrets_for_public_comment")
    secret = "sk-live-public-comment-leak-test-token"
    body = redact(f"contact us with {secret} please")
    assert secret not in body
    assert "sk-live" not in body
