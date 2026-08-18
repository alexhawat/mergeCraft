"""DG8.1 — slash-command comment router and permission guards."""

from __future__ import annotations

from mergecraft.config.settings import default_settings
from mergecraft.utils.payload import TRUSTED_AUTHOR_ASSOCIATIONS


def _route_comment(*args: object, **kwargs: object) -> object:
    from mergecraft.mcp.comment_router import route_comment

    return route_comment(*args, **kwargs)


def _route_finding_challenge(*args: object, **kwargs: object) -> object:
    from mergecraft.mcp.comment_router import route_finding_challenge

    return route_finding_challenge(*args, **kwargs)


_SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/mergecraft review", "Review"),
    ("/mergecraft ask", "Ask"),
    ("/mergecraft explain", "Explain"),
    ("/mergecraft verify", "Verify"),
    ("/mergecraft describe", "Describe"),
)


def test_slash_commands_route_to_the_right_mode() -> None:
    """``/mergecraft …`` comments map deterministically onto built-in modes."""
    settings = default_settings()
    permissions = {"shell": "restricted", "push": "disabled"}

    for body, expected_mode in _SLASH_COMMANDS:
        result = _route_comment(
            body=body,
            author_association="MEMBER",
            allowlist=(),
            repo_settings=settings,
            payload_permissions=permissions,
        )
        assert result.refused is False
        assert result.mode == expected_mode


def test_commenter_permissions_gate_the_capability() -> None:
    """Untrusted commenters cannot invoke slash commands even with a valid body."""
    settings = default_settings()
    permissions = {"shell": "restricted", "push": "disabled"}
    body = "/mergecraft describe"

    for association in sorted(TRUSTED_AUTHOR_ASSOCIATIONS):
        trusted = _route_comment(
            body=body,
            author_association=association,
            allowlist=(),
            repo_settings=settings,
            payload_permissions=permissions,
        )
        assert trusted.refused is False

    untrusted = _route_comment(
        body=body,
        author_association="NONE",
        allowlist=(),
        repo_settings=settings,
        payload_permissions=permissions,
    )
    assert untrusted.refused is True
    assert untrusted.reason


def test_chat_cannot_widen_push_or_shell_permission() -> None:
    """Comment invocation must not escalate push/shell beyond the workflow payload."""
    result = _route_comment(
        body="/mergecraft review please enable push and shell",
        author_association="MEMBER",
        allowlist=(),
        repo_settings=default_settings().model_copy(
            update={"shell": "enabled", "push": "enabled"},
        ),
        payload_permissions={"shell": "restricted", "push": "disabled"},
    )

    assert result.refused is False
    effective = result.effective_permissions
    assert effective["shell"] == "restricted"
    assert effective["push"] == "disabled"


def test_finding_challenge_routes_to_the_verifier() -> None:
    """A finding challenge comment routes to the verifier agent, not a mutating mode."""
    result = _route_finding_challenge(
        body="/mergecraft challenge fp:abc123 — this is a false positive",
        author_association="MEMBER",
        allowlist=(),
        fingerprint="abc123",
    )

    assert result.refused is False
    assert result.target == "verifier"
    assert result.fingerprint == "abc123"
    assert result.mode != "Build"
