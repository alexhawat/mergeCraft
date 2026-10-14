"""W14 / W15 — SCM webhook security, idempotency, conformance (#361).

Out of scope (no tests that force impl): new SCM providers (Bitbucket, Azure
DevOps, Gitea, Gerrit).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.cd_batch import (
    SUPPORTED_WEBHOOK_PROVIDERS,
    WEBHOOK_MODULE,
    d10_root_callback_owns_globals,
    require_callable,
    require_module,
)


def test_w15_does_not_fold_webhooks_into_root_callback() -> None:
    """D10 — webhook handling is not a root-callback flag."""
    root_block = d10_root_callback_owns_globals()
    assert "webhook" not in root_block.casefold()
    assert "supply-chain" not in root_block
    assert "supply_chain" not in root_block


def test_webhook_module_covers_github_and_gitlab_only() -> None:
    """Happy: supported providers are GitHub and GitLab; Bitbucket stays out."""
    module = require_module(WEBHOOK_MODULE)
    providers = frozenset(module.SUPPORTED_WEBHOOK_PROVIDERS)
    assert providers == SUPPORTED_WEBHOOK_PROVIDERS
    verify = require_callable(module, "verify_webhook_signature")
    with pytest.raises(
        (ValueError, LookupError, PermissionError),
        match=r"unsupported|github|gitlab|bitbucket",
    ):
        verify("bitbucket", headers={}, body=b"", secret="secret")


@pytest.mark.parametrize("provider", sorted(SUPPORTED_WEBHOOK_PROVIDERS))
def test_webhook_signature_verification_accepts_a_valid_payload(provider: str) -> None:
    """Happy: each supported provider verifies a matching signature."""
    module = require_module(WEBHOOK_MODULE)
    verify = require_callable(module, "verify_webhook_signature")
    signed = require_callable(module, "sign_webhook_payload")(
        provider, body=b'{"ok":true}', secret="test-secret"
    )
    verify(provider, headers=signed, body=b'{"ok":true}', secret="test-secret")


def test_webhook_signature_verification_rejects_a_bad_hmac() -> None:
    """Error: invalid GitHub HMAC names the failure (type + message)."""
    module = require_module(WEBHOOK_MODULE)
    verify = require_callable(module, "verify_webhook_signature")
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError),
        match=r"signature|hmac|unauthor",
    ):
        verify(
            "github",
            headers={"X-Hub-Signature-256": "sha256=deadbeef"},
            body=b'{"ok":true}',
            secret="test-secret",
        )


def test_webhook_signature_verification_rejects_an_empty_secret() -> None:
    """Error: a blank/whitespace secret fails closed, even if HMAC would match."""
    module = require_module(WEBHOOK_MODULE)
    verify = require_callable(module, "verify_webhook_signature")
    signed = require_callable(module, "sign_webhook_payload")(
        "github", body=b'{"ok":true}', secret=""
    )
    with pytest.raises(PermissionError, match=r"missing webhook secret"):
        verify("github", headers=signed, body=b'{"ok":true}', secret="")
    with pytest.raises(PermissionError, match=r"missing webhook secret"):
        verify("gitlab", headers={"X-Gitlab-Token": ""}, body=b"{}", secret="  ")


def test_gitlab_webhook_token_is_shared_secret_equality_not_hmac() -> None:
    """GitLab ``X-Gitlab-Token`` is timing-safe equality, not HMAC of the body."""
    module = require_module(WEBHOOK_MODULE)
    verify = require_callable(module, "verify_webhook_signature")
    signed = require_callable(module, "sign_webhook_payload")(
        "gitlab", body=b'{"ok":true}', secret="gitlab-shared-secret"
    )
    verify(
        "gitlab",
        headers=signed,
        body=b'{"different":"body"}',
        secret="gitlab-shared-secret",
    )
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError),
        match=r"signature|hmac|unauthor|secret",
    ):
        verify(
            "gitlab",
            headers={"X-Gitlab-Token": "wrong-token"},
            body=b'{"ok":true}',
            secret="gitlab-shared-secret",
        )


def test_webhook_rate_limit_is_handled_without_dropping_the_event() -> None:
    """Edge: a 429 from the provider is surfaced, not silently dropped."""
    module = require_module(WEBHOOK_MODULE)
    handle = require_callable(module, "handle_webhook_rate_limit")
    outcome = handle(provider="github", status_code=429, retry_after_seconds=1)
    retryable = getattr(outcome, "retryable", None)
    if retryable is None:
        retryable = outcome.get("retryable")
    assert retryable is True
    assert "429" in str(outcome) or "rate" in str(outcome).casefold()


def test_provider_permission_checks_are_asserted_per_adapter() -> None:
    """Happy: GitHub and GitLab adapters expose permission probes."""
    module = require_module(WEBHOOK_MODULE)
    probe = require_callable(module, "assert_provider_permissions")
    for provider in sorted(SUPPORTED_WEBHOOK_PROVIDERS):
        probe(provider)


def test_provider_conformance_uses_identical_review_semantics() -> None:
    """Integration: GitHub and GitLab webhook events map to the same review."""
    module = require_module(WEBHOOK_MODULE)
    conform = require_callable(module, "conforming_review_request")
    github = conform("github", event="pull_request", body={"action": "opened", "number": 1})
    gitlab = conform("gitlab", event="Merge Request Hook", body={"object_kind": "merge_request"})
    github_mode = getattr(github, "mode", None) or github.get("mode")
    gitlab_mode = getattr(gitlab, "mode", None) or gitlab.get("mode")
    assert github_mode == gitlab_mode
    assert github_mode in {"Review", "IncrementalReview"}


def test_scm_adapters_cannot_bypass_review_only_restrictions() -> None:
    """Error: webhook-driven adapters still cannot edit / commit / push."""
    module = require_module(WEBHOOK_MODULE)
    guard = require_callable(module, "assert_review_only_webhook_capabilities")
    with pytest.raises(
        (PermissionError, RuntimeError, ValueError),
        match=r"review-only|commit|push|edit",
    ):
        guard(requested_capability="commit")


def test_webhook_module_does_not_import_ci_gitlab_log_adapter() -> None:
    """#361 out of scope — webhook code must not import CI GitLab logs."""
    module = require_module(WEBHOOK_MODULE)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "ci.providers.gitlab" not in source
    assert "mergecraft.ci.providers.gitlab" not in source
