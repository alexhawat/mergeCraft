"""W14 / W15 — SCM webhook security, idempotency, conformance (#361).

Out of scope (no tests that force impl): new SCM providers (Bitbucket, Azure
DevOps, Gitea, Gerrit); ``ci/providers/gitlab.py`` is CI logs, not an SCM
adapter.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.ci.workflow_support import REPO_ROOT
from tests.support.cd_batch import (
    SUPPORTED_WEBHOOK_PROVIDERS,
    WEBHOOK_MODULE,
    d10_root_callback_owns_globals,
    require_callable,
    require_module,
)
from tests.support.dead_package_wiring import SRC_ROOT


def test_ci_gitlab_log_adapter_is_not_an_scm_webhook_surface() -> None:
    """#361 out of scope — ``ci/providers/gitlab.py`` stays a CI log reader."""
    ci_gitlab = REPO_ROOT / "src" / "mergecraft" / "ci" / "providers" / "gitlab.py"
    assert ci_gitlab.is_file()
    scm_init = (SRC_ROOT / "scm" / "__init__.py").read_text(encoding="utf-8")
    assert "ci.providers.gitlab" not in scm_init
    assert "ci/providers/gitlab" not in scm_init


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


def test_webhook_replay_protection_rejects_stale_or_reused_delivery() -> None:
    """Error: replay protection rejects a stale timestamp or reused nonce."""
    module = require_module(WEBHOOK_MODULE)
    check = require_callable(module, "reject_webhook_replay")
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError),
        match=r"replay|timestamp|nonce|stale",
    ):
        check(
            provider="github",
            headers={"X-Hub-Signature-256": "sha256=00", "X-GitHub-Delivery": "dup"},
            body=b"{}",
            received_at_skew_seconds=86_400,
        )


def test_webhook_event_processing_fails_closed_without_delivery_id() -> None:
    """Error: missing delivery id is rejected, not stored as anonymous."""
    module = require_module(WEBHOOK_MODULE)
    process = require_callable(module, "process_webhook_event")
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError), match=r"missing webhook delivery id"
    ):
        process(provider="github", delivery_id="", event="pull_request", body={"action": "opened"})
    check = require_callable(module, "reject_webhook_replay")
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError), match=r"missing webhook delivery id"
    ):
        check(
            provider="github",
            headers={"X-Hub-Signature-256": "sha256=00"},
            body=b"{}",
            received_at_skew_seconds=0,
        )


def test_webhook_event_processing_is_idempotent_on_delivery_id() -> None:
    """Edge: the same delivery id is processed once."""
    module = require_module(WEBHOOK_MODULE)
    process = require_callable(module, "process_webhook_event")
    first = process(
        provider="github",
        delivery_id="abc-1",
        event="pull_request",
        body={"action": "opened"},
    )
    second = process(
        provider="github",
        delivery_id="abc-1",
        event="pull_request",
        body={"action": "opened"},
    )
    duplicate = getattr(second, "duplicate", None)
    if duplicate is None:
        duplicate = second.get("duplicate")
    assert duplicate is True
    first_id = getattr(first, "result_id", None) or (
        first.get("result_id") if isinstance(first, dict) else None
    )
    second_id = getattr(second, "result_id", None) or (
        second.get("result_id") if isinstance(second, dict) else None
    )
    if first_id is not None:
        assert second_id == first_id


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


def test_webhook_ingress_rejects_invalid_hmac_before_processing() -> None:
    """Error: the HTTP ingress refuses a bad signature and does not process."""
    from mergecraft.scm.ingress import accept_webhook

    with pytest.raises(
        (ValueError, PermissionError, RuntimeError),
        match=r"signature|hmac|unauthor",
    ):
        accept_webhook(
            "github",
            headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Delivery": "ing-1"},
            body=b'{"ok":true}',
            secret="test-secret",
        )


def test_webhook_ingress_verifies_then_processes_a_valid_payload() -> None:
    """Happy: ingress HMAC + replay check then processes the delivery once."""
    from mergecraft.scm.ingress import accept_webhook

    module = require_module(WEBHOOK_MODULE)
    body = b'{"action":"opened"}'
    signed = require_callable(module, "sign_webhook_payload")(
        "github", body=body, secret="ingress-secret"
    )
    headers = {**signed, "X-GitHub-Delivery": "ing-valid-1", "X-GitHub-Event": "pull_request"}
    first = accept_webhook("github", headers=headers, body=body, secret="ingress-secret")
    assert first.duplicate is False
    with pytest.raises(
        (ValueError, PermissionError, RuntimeError),
        match=r"replay|timestamp|nonce|stale",
    ):
        accept_webhook("github", headers=headers, body=body, secret="ingress-secret")


def test_http_webhook_route_rejects_empty_secret_for_github_and_gitlab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP /webhooks/{provider} fails closed when MERGECRAFT_WEBHOOK_SECRET is unset."""
    from mergecraft.mcp.server import create_mcp_app
    from mergecraft.scm.webhooks import sign_webhook_payload

    monkeypatch.delenv("MERGECRAFT_WEBHOOK_SECRET", raising=False)
    client = TestClient(create_mcp_app([]))
    body = b'{"ok":true}'
    github_hmac = sign_webhook_payload("github", body=body, secret="")
    github = client.post(
        "/webhooks/github",
        content=body,
        headers={
            **github_hmac,
            "X-GitHub-Delivery": "http-empty-secret-gh",
            "X-GitHub-Event": "ping",
        },
    )
    assert github.status_code == 401
    assert "secret" in github.json()["error"].casefold()
    gitlab = client.post(
        "/webhooks/gitlab",
        content=body,
        headers={
            "X-Gitlab-Token": "",
            "X-Gitlab-Event-UUID": "http-empty-secret-gl",
            "X-Gitlab-Event": "Push Hook",
        },
    )
    assert gitlab.status_code == 401
    assert "secret" in gitlab.json()["error"].casefold()


def test_http_webhook_route_accepts_signed_github_and_gitlab_deliveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP /webhooks/{provider} authenticates both providers when a secret is set."""
    from mergecraft.mcp.server import create_mcp_app
    from mergecraft.scm.webhooks import sign_webhook_payload

    secret = "route-secret"
    monkeypatch.setenv("MERGECRAFT_WEBHOOK_SECRET", secret)
    client = TestClient(create_mcp_app([]))
    body = b'{"ok":true}'
    github = client.post(
        "/webhooks/github",
        content=body,
        headers={
            **sign_webhook_payload("github", body=body, secret=secret),
            "X-GitHub-Delivery": "http-ok-gh",
            "X-GitHub-Event": "ping",
        },
    )
    assert github.status_code == 200
    assert github.json()["duplicate"] is False
    gitlab = client.post(
        "/webhooks/gitlab",
        content=body,
        headers={
            **sign_webhook_payload("gitlab", body=body, secret=secret),
            "X-Gitlab-Event-UUID": "http-ok-gl",
            "X-Gitlab-Event": "Push Hook",
        },
    )
    assert gitlab.status_code == 200
    assert gitlab.json()["duplicate"] is False


def test_webhook_module_does_not_import_ci_gitlab_log_adapter() -> None:
    """#361 out of scope — webhook code must not import CI GitLab logs."""
    module = require_module(WEBHOOK_MODULE)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "ci.providers.gitlab" not in source
    assert "mergecraft.ci.providers.gitlab" not in source
