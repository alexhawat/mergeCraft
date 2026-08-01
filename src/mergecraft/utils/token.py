"""Token resolution — GITHUB_TOKEN / installation token (optional App JWT)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.types import PushPermission, XrepoConfig

_mcp_token_value: str | None = None
_mcp_token_refresh: Callable[[str], Awaitable[str]] | None = None


def get_job_token() -> str:
    """Job-scoped token from action input / GH_TOKEN / GITHUB_TOKEN."""
    input_token = os.environ.get("INPUT_TOKEN", "").strip()
    if input_token:
        return input_token
    fallback = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if fallback:
        return fallback
    msg = "token input is required (set INPUT_TOKEN, GH_TOKEN, or GITHUB_TOKEN)"
    raise ValueError(msg)


def get_github_installation_token() -> str:
    if not _mcp_token_value:
        msg = "tokens not set — call resolve_tokens first"
        raise RuntimeError(msg)
    return _mcp_token_value


def get_mcp_token_refresh() -> Callable[[str], Awaitable[str]] | None:
    return _mcp_token_refresh


@dataclass(slots=True)
class TokenRef:
    git_token: str
    mcp_token: str
    read_token: str | None = None
    refresh_git_token: Callable[[str], Awaitable[str]] | None = None
    _dispose: Callable[[], Awaitable[None]] | None = None

    async def aclose(self) -> None:
        if self._dispose:
            await self._dispose()

    async def __aenter__(self) -> TokenRef:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


async def revoke_installation_token(token: str) -> None:
    api_url = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.delete(
                f"{api_url}/installation/token",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        logger.debug("» installation token revoked")
    except Exception as exc:
        logger.info("Failed to revoke installation token: {}", exc)


def _app_jwt() -> str | None:
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    if not app_id or not private_key:
        return None
    try:
        import jwt
    except ImportError:
        logger.warning("pyjwt not available — cannot mint App JWT")
        return None
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": app_id}
    key = private_key.replace("\\n", "\n")
    return jwt.encode(payload, key, algorithm="RS256")


async def acquire_installation_token(
    *,
    repos: list[str] | None = None,
    permissions: dict[str, str] | None = None,
    installation_id: int | None = None,
) -> str:
    """Mint a GitHub App installation token from App credentials in the env."""
    api_url = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    jwt_token = _app_jwt()
    if not jwt_token:
        msg = "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY are required to mint an installation token"
        raise ValueError(msg)

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        inst_id = installation_id
        if inst_id is None:
            env_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "").strip()
            if env_id:
                inst_id = int(env_id)
            else:
                repo = os.environ.get("GITHUB_REPOSITORY", "")
                if "/" not in repo:
                    msg = "GITHUB_REPOSITORY or GITHUB_APP_INSTALLATION_ID required"
                    raise ValueError(msg)
                owner, name = repo.split("/", 1)
                resp = await client.get(
                    f"{api_url}/repos/{owner}/{name}/installation",
                    headers=headers,
                )
                resp.raise_for_status()
                inst_id = int(resp.json()["id"])

        body: dict[str, Any] = {}
        if permissions:
            body["permissions"] = permissions
        if repos:
            # GitHub expects bare repo names for repository_ids path; for names use repositories
            body["repositories"] = [r.split("/")[-1] for r in repos]

        resp = await client.post(
            f"{api_url}/app/installations/{inst_id}/access_tokens",
            headers=headers,
            json=body or None,
        )
        resp.raise_for_status()
        token = resp.json()["token"]
        assert isinstance(token, str)
        return token


async def resolve_tokens(
    *,
    push: PushPermission | str = "restricted",
    xrepo: XrepoConfig | dict[str, Any] | None = None,
) -> TokenRef:
    """Resolve git + MCP tokens for the run (local BYOK — no mergecraft.com)."""
    global _mcp_token_value, _mcp_token_refresh

    if _mcp_token_value:
        msg = "tokens are already resolved"
        raise RuntimeError(msg)

    external = os.environ.get("GH_TOKEN")
    if external:
        _mcp_token_value = external
        logger.info("» using external GH_TOKEN for both git and MCP")
        read = external if xrepo else None

        async def _noop_dispose() -> None:
            global _mcp_token_value, _mcp_token_refresh
            _mcp_token_value = None
            _mcp_token_refresh = None

        return TokenRef(
            git_token=external,
            mcp_token=external,
            read_token=read,
            _dispose=_noop_dispose,
        )

    # Prefer a pre-minted installation token, else job token.
    job = get_job_token()
    minted: str | None = None
    try:
        if os.environ.get("GITHUB_APP_ID") and os.environ.get("GITHUB_APP_PRIVATE_KEY"):
            write_repos = None
            if isinstance(xrepo, dict):
                write_repos = xrepo.get("write")
            elif xrepo is not None:
                write_repos = list(xrepo.write)
            git_perms = (
                {"contents": "read"}
                if push == "disabled"
                else {"contents": "write", "workflows": "write"}
            )
            minted = await acquire_installation_token(
                repos=write_repos,
                permissions=git_perms,
            )
            logger.info("» acquired installation token via App JWT")
    except Exception as exc:
        logger.debug("» App JWT mint skipped: {}", exc)

    token = minted or job
    _mcp_token_value = token

    async def _dispose() -> None:
        global _mcp_token_value, _mcp_token_refresh
        current = _mcp_token_value
        _mcp_token_value = None
        _mcp_token_refresh = None
        if minted and current:
            await revoke_installation_token(current)

    return TokenRef(
        git_token=token,
        mcp_token=token,
        read_token=token if xrepo else None,
        _dispose=_dispose,
    )


# Aliases matching CLI / companion action naming
acquire_new_token = acquire_installation_token
revoke_github_installation_token = revoke_installation_token

__all__ = [
    "TokenRef",
    "acquire_installation_token",
    "acquire_new_token",
    "get_github_installation_token",
    "get_job_token",
    "get_mcp_token_refresh",
    "resolve_tokens",
    "revoke_github_installation_token",
    "revoke_installation_token",
]
