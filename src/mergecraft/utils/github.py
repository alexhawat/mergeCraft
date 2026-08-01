"""Async httpx GitHub REST + GraphQL client (Octokit-like thin wrapper)."""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from mergecraft.config.settings import (
    RepoSettings,
    RunContextData,
    load_repo_settings,
)

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_ACCEPT = "application/vnd.github+json"
DEFAULT_API_VERSION = "2022-11-28"


def _as_dict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        msg = f"expected JSON object, got {type(data).__name__}"
        raise TypeError(msg)
    return data


def _as_list(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


class RepoContext:
    """Parsed ``owner`` / ``name`` from ``GITHUB_REPOSITORY``."""

    __slots__ = ("name", "owner")

    def __init__(self, owner: str, name: str) -> None:
        self.owner = owner
        self.name = name


def parse_repo_context(repository: str | None = None) -> RepoContext:
    """Parse repository context from ``GITHUB_REPOSITORY`` (``owner/name``)."""
    github_repo = repository if repository is not None else os.environ.get("GITHUB_REPOSITORY")
    if not github_repo:
        msg = "GITHUB_REPOSITORY environment variable is required"
        raise ValueError(msg)
    parts = github_repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        msg = f"Invalid GITHUB_REPOSITORY format: {github_repo}. Expected 'owner/repo'"
        raise ValueError(msg)
    return RepoContext(owner=parts[0], name=parts[1])


def _is_transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class GitHubClient:
    """Thin async GitHub REST + GraphQL client backed by ``httpx.AsyncClient``."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_API_URL,
        timeout: float = 60.0,
        user_agent: str = "mergeCraft",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        headers = {
            "Accept": DEFAULT_ACCEPT,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": DEFAULT_API_VERSION,
            "User-Agent": user_agent,
        }
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @retry(
        retry=retry_if_exception(_is_transient_http_error),
        wait=wait_fixed(0.5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Perform a REST request and return parsed JSON (or ``None`` for 204)."""
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
        )
        if response.status_code >= 400:
            logger.debug("GitHub {} {} -> {}", method, path, response.status_code)
            response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, **kwargs)

    async def graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query against ``/graphql``."""
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        data = await self.post("/graphql", json=payload)
        if not isinstance(data, dict):
            msg = "unexpected GraphQL response"
            raise RuntimeError(msg)
        if data.get("errors"):
            msg = f"GraphQL errors: {data['errors']}"
            raise RuntimeError(msg)
        return data.get("data") or {}

    # --- repos ---

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return _as_dict(await self.get(f"/repos/{owner}/{repo}"))

    async def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        return _as_dict(await self.get(f"/repos/{owner}/{repo}/commits/{ref}"))

    # --- issues ---

    async def get_issue(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        return _as_dict(await self.get(f"/repos/{owner}/{repo}/issues/{issue_number}", **kwargs))

    async def create_issue(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, **extra}
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = labels
        return _as_dict(await self.post(f"/repos/{owner}/{repo}/issues", json=payload))

    async def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        **fields: Any,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.patch(f"/repos/{owner}/{repo}/issues/{issue_number}", json=fields)
        )

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return _as_list(
            await self.get(
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                **kwargs,
            )
        )

    async def get_issue_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.get(f"/repos/{owner}/{repo}/issues/comments/{comment_id}", **kwargs)
        )

    async def create_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.post(
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                json={"body": body},
            )
        )

    async def update_issue_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.patch(
                f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
                json={"body": body},
            )
        )

    async def add_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        labels: list[str],
    ) -> list[dict[str, Any]]:
        return _as_list(
            await self.post(
                f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
                json={"labels": labels},
            )
        )

    # --- pull requests ---

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return _as_dict(await self.get(f"/repos/{owner}/{repo}/pulls/{pull_number}"))

    async def update_pull(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        **fields: Any,
    ) -> dict[str, Any]:
        return _as_dict(await self.patch(f"/repos/{owner}/{repo}/pulls/{pull_number}", json=fields))

    async def list_pull_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return _as_list(
            await self.get(f"/repos/{owner}/{repo}/pulls/{pull_number}/files", **kwargs)
        )

    async def list_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return _as_list(
            await self.get(f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews", **kwargs)
        )

    async def get_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        review_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.get(
                f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}",
                **kwargs,
            )
        )

    async def create_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        **fields: Any,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.post(
                f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
                json=fields,
            )
        )

    async def submit_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        review_id: int,
        *,
        event: str,
        body: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"event": event}
        if body is not None:
            payload["body"] = body
        return _as_dict(
            await self.post(
                f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}/events",
                json=payload,
            )
        )

    async def delete_pending_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        review_id: int,
    ) -> dict[str, Any] | None:
        data = await self.delete(f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}")
        return None if data is None else _as_dict(data)

    async def get_review_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.get(
                f"/repos/{owner}/{repo}/pulls/comments/{comment_id}",
                **kwargs,
            )
        )

    async def create_review_comment_reply(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.post(
                f"/repos/{owner}/{repo}/pulls/comments/{comment_id}/replies",
                json={"body": body},
            )
        )

    # --- statuses / checks ---

    async def create_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        *,
        state: str,
        context: str,
        description: str | None = None,
        target_url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"state": state, "context": context}
        if description is not None:
            payload["description"] = description
        if target_url is not None:
            payload["target_url"] = target_url
        return _as_dict(await self.post(f"/repos/{owner}/{repo}/statuses/{sha}", json=payload))

    async def list_check_suites_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return _as_dict(
            await self.get(f"/repos/{owner}/{repo}/commits/{ref}/check-suites", **kwargs)
        )

    async def get_check_suite(
        self,
        owner: str,
        repo: str,
        check_suite_id: int,
    ) -> dict[str, Any]:
        return _as_dict(await self.get(f"/repos/{owner}/{repo}/check-suites/{check_suite_id}"))


async def resolve_run_context_data(
    client: GitHubClient,
    *,
    settings: RepoSettings | None = None,
    settings_path: str | None = None,
    repository: str | None = None,
) -> RunContextData:
    """Build ``RunContextData`` from local settings + GitHub ``repos.get``.

    Does **not** call mergecraft.com — ``api_token`` is empty, ``plan`` is ``none``,
    and ``oss`` is derived from ``repo.private``.
    """
    repo_ctx = parse_repo_context(repository)
    repo_settings = settings if settings is not None else load_repo_settings(settings_path)

    data = await client.get_repo(repo_ctx.owner, repo_ctx.name)
    private = bool(data.get("private"))

    return RunContextData.model_validate(
        {
            "repo": {"owner": repo_ctx.owner, "name": repo_ctx.name, "data": data},
            "repo_settings": repo_settings.model_dump(by_alias=True),
            "api_token": "",
            "oss": not private,
            "plan": "none",
            "proxy_model": None,
            "db_secrets": None,
        }
    )
