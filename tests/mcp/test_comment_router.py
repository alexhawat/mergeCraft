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


def test_review_slash_command_routes_to_review_mode() -> None:
    """``/mergecraft review`` maps onto the built-in Review mode."""
    settings = default_settings()
    permissions = {"shell": "restricted", "push": "disabled"}

    result = _route_comment(
        body="/mergecraft review",
        author_association="MEMBER",
        allowlist=(),
        repo_settings=settings,
        payload_permissions=permissions,
    )
    assert result.refused is False
    assert result.mode == "Review"


def test_staged_slash_commands_refuse_until_modes_exist() -> None:
    """Ask/explain/verify/describe refuse routing until those modes are built-in."""
    settings = default_settings()
    permissions = {"shell": "restricted", "push": "disabled"}

    for body in (
        "/mergecraft ask",
        "/mergecraft explain",
        "/mergecraft verify",
        "/mergecraft describe",
    ):
        result = _route_comment(
            body=body,
            author_association="MEMBER",
            allowlist=(),
            repo_settings=settings,
            payload_permissions=permissions,
        )
        assert result.refused is True
        assert result.reason == "mode_not_implemented"
        assert result.mode is None


def test_commenter_permissions_gate_the_capability() -> None:
    """Untrusted commenters cannot invoke slash commands even with a valid body."""
    settings = default_settings()
    permissions = {"shell": "restricted", "push": "disabled"}
    body = "/mergecraft review"

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


def test_comment_router_is_a_staged_library_surface() -> None:
    """DG8.2 library extraction — routing is not wired to Action dispatch yet."""
    import ast
    import inspect

    import mergecraft.main as main_mod
    import mergecraft.mcp.comment_router as router

    doc = router.__doc__ or ""
    assert "library surface" in doc.lower()
    assert "select_mode" in doc or "dispatch" in doc

    main_source = inspect.getsource(main_mod)
    assert "comment_router" not in main_source

    tree = ast.parse(main_source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert "mergecraft.mcp.comment_router" not in imported_modules
    assert not any(
        module == "mergecraft.pr" or module.startswith("mergecraft.pr.")
        for module in imported_modules
    )
