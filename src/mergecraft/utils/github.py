"""Async httpx GitHub REST + GraphQL client (Octokit-like thin wrapper)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final

import httpx
from loguru import logger
from tenacity import retry

from mergecraft.config.settings import (
    RepoSettings,
    RunContextData,
    load_repo_settings,
)
from mergecraft.scm.types import ListedItems
from mergecraft.utils.retry_policy import (
    DEFAULT_STOP,
    DEFAULT_WAIT,
    is_transient_http_error,
    retry_transient_safe_methods,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_ACCEPT = "application/vnd.github+json"
DEFAULT_API_VERSION = "2022-11-28"
GITHUB_LIST_PAGE_SIZE: Final[int] = 100
GITHUB_LIST_MAX_PAGES: Final[int] = 50


def _as_dict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        msg = f"expected JSON object, got {type(data).__name__}"
        raise TypeError(msg)
    return data


def _as_list(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        msg = f"expected JSON array, got {type(data).__name__}"
        raise TypeError(msg)
    items: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            msg = f"expected JSON object rows, got {type(item).__name__}"
            raise TypeError(msg)
        items.append(item)
    return items


async def paginate_github_list_pages(
    fetch_page: Callable[[int], Awaitable[Any]],
    *,
    item_key: str,
    page_size: int = GITHUB_LIST_PAGE_SIZE,
    max_pages: int = GITHUB_LIST_MAX_PAGES,
) -> ListedItems:
    """Follow GitHub list pages until a short page or ``max_pages``.

    Each ``fetch_page(page)`` should return a JSON object with ``item_key``.
    A full page of ``page_size`` continues; a shorter page ends the walk so
    items past 100 are not silently dropped.

    ``incomplete`` is True when the walk hit ``max_pages`` on a full page,
    the payload was not an object, ``item_key`` was missing or not a list,
    a JSON array was returned where an object was expected, or non-dict
    rows were dropped — callers must not treat that as a complete catalog.
    """
    collected: list[dict[str, Any]] = []
    incomplete = False
    total_count: int | None = None
    for page in range(1, max_pages + 1):
        payload = await fetch_page(page)
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("total_count"), int)
            and total_count is None
        ):
            total_count = payload["total_count"]
        if isinstance(payload, dict):
            raw_items: Any = payload.get(item_key)
            if not isinstance(raw_items, list):
                logger.warning(
                    "github list pagination: missing or non-list {} on object payload; "
                    "stopping without treating the list as complete",
                    item_key,
                )
                incomplete = True
                break
        else:
            logger.warning(
                "github list pagination: unexpected {} payload for {}; "
                "stopping without treating the list as complete",
                type(payload).__name__,
                item_key,
            )
            incomplete = True
            break
        page_len = len(raw_items)
        batch = [item for item in raw_items if isinstance(item, dict)]
        if len(batch) != page_len:
            incomplete = True
        collected.extend(batch)
        if page_len < page_size:
            break
        if page == max_pages:
            logger.warning(
                "github list pagination: hit max_pages={} with a full page of {} {}; "
                "results may be truncated",
                max_pages,
                page_size,
                item_key,
            )
            incomplete = True
    return ListedItems(items=collected, incomplete=incomplete, total_count=total_count)


async def paginate_github_bare_array(
    fetch_page: Callable[[int], Awaitable[Any]],
    *,
    path_for_log: str,
    page_size: int = GITHUB_LIST_PAGE_SIZE,
    max_pages: int = GITHUB_LIST_MAX_PAGES,
    strict_rows: bool = True,
) -> list[dict[str, Any]]:
    """Walk bare JSON array list pages returned by GitHub REST endpoints."""
    collected: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = await fetch_page(page)
        if strict_rows:
            batch = _as_list(payload)
        elif isinstance(payload, list):
            batch = [item for item in payload if isinstance(item, dict)]
        else:
            batch = []
        collected.extend(batch)
        if len(batch) < page_size:
            break
        if page == max_pages:
            logger.warning(
                "github list pagination: hit max_pages={} for {}; catalog is truncated",
                max_pages,
                path_for_log,
            )
    return collected


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
    """Backward-compatible alias for ``is_transient_http_error`` (W9 tests)."""
    return is_transient_http_error(exc)


def _default_api_base_url() -> str:
    """Resolve the GitHub REST base URL (GHES / Actions / E2E mock).

    Honours the runner-provided ``GITHUB_API_URL`` (standard GitHub Actions /
    GHES env) before falling back to ``https://api.github.com``. The W11 E2E
    gate points this at a fixture mock so PR CI never hits live GitHub or
    live LLMs (D6).
    """
    return (os.environ.get("GITHUB_API_URL") or DEFAULT_API_URL).rstrip("/")


def usable_github_token(token: str) -> str:
    """Return a non-empty GitHub token, or ``""`` when missing or whitespace (#469)."""
    return token.strip()


class GitHubClient:
    """Thin async GitHub REST + GraphQL client backed by ``httpx.AsyncClient``."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        user_agent: str = "mergeCraft",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = usable_github_token(token)
        self.base_url = (base_url or _default_api_base_url()).rstrip("/")
        self._owns_client = client is None
        headers = {
            "Accept": DEFAULT_ACCEPT,
            "X-GitHub-Api-Version": DEFAULT_API_VERSION,
            "User-Agent": user_agent,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
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
        retry=retry_transient_safe_methods(),
        wait=DEFAULT_WAIT,
        stop=DEFAULT_STOP,
        reraise=True,
    )
    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        """Token-gated HTTP send with the same retry policy as :meth:`request`."""
        if not self.token:
            msg = "GitHub token is missing; cannot call the GitHub API"
            raise ValueError(msg)
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
            follow_redirects=follow_redirects,
        )
        if response.status_code >= 400:
            logger.debug("GitHub {} {} -> {}", method, path, response.status_code)
            response.raise_for_status()
        return response

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Perform a REST request and return parsed JSON (or ``None`` for 204).

        Safe methods (GET/HEAD/OPTIONS) retry on transient 429/5xx/transport
        errors with bounded exponential backoff + jitter. Mutations
        (POST/PATCH/PUT/DELETE) are never retried blindly (W9.3 / ``#34``).
        """
        response = await self._send(method, path, params=params, json=json, headers=headers)
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

    async def _paginate_bare_array(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Walk GitHub list pages for endpoints that return a bare JSON array."""
        extra_params = kwargs.pop("params", None) or {}

        async def _fetch_page(page: int) -> Any:
            params = {**extra_params, "per_page": GITHUB_LIST_PAGE_SIZE, "page": page}
            return await self.get(path, params=params, **kwargs)

        return await paginate_github_bare_array(_fetch_page, path_for_log=path)

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
        return await self._paginate_bare_array(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            **kwargs,
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

    async def list_issues(
        self,
        owner: str,
        repo: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return _as_list(await self.get(f"/repos/{owner}/{repo}/issues", **kwargs))

    async def create_label(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        color: str = "ededed",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a repository label; raises 422 when it already exists."""
        payload: dict[str, Any] = {"name": name, "color": color}
        if description is not None:
            payload["description"] = description
        return _as_dict(await self.post(f"/repos/{owner}/{repo}/labels", json=payload))

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
        return await self._paginate_bare_array(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
            **kwargs,
        )

    async def list_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return await self._paginate_bare_array(
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            **kwargs,
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
        path = f"/repos/{owner}/{repo}/commits/{ref}/check-suites"
        extra = kwargs.pop("params", None) or {}

        async def _fetch_page(page: int) -> Any:
            params = {
                **extra,
                "per_page": GITHUB_LIST_PAGE_SIZE,
                "page": page,
            }
            return await self.get(path, params=params, **kwargs)

        listed = await paginate_github_list_pages(_fetch_page, item_key="check_suites")
        total = listed.total_count
        if total is None and not listed.incomplete:
            total = len(listed.items)
        return {"total_count": total, "check_suites": listed.items}

    async def get_check_suite(
        self,
        owner: str,
        repo: str,
        check_suite_id: int,
    ) -> dict[str, Any]:
        return _as_dict(await self.get(f"/repos/{owner}/{repo}/check-suites/{check_suite_id}"))

    async def list_check_runs_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        **kwargs: Any,
    ) -> ListedItems:
        """List individual check runs for a commit ref (#36 gate evidence).

        ``list_check_suites_for_ref`` returns suites, whose conclusion is the
        rollup of every job in them. Gate substitution needs the *named* run —
        a repo declaring ``lint: "Verify (lint)"`` is pointing at one job, not
        at whether the whole suite went green.
        """
        extra = kwargs.pop("params", None) or {}

        async def _fetch_page(page: int) -> Any:
            params = {
                **extra,
                "per_page": GITHUB_LIST_PAGE_SIZE,
                "page": page,
            }
            return await self.get(
                f"/repos/{owner}/{repo}/commits/{ref}/check-runs",
                params=params,
                **kwargs,
            )

        listed = await paginate_github_list_pages(_fetch_page, item_key="check_runs")
        # Never overwrite GitHub's total_count with len(items): a truncated
        # walk would then look complete.
        total = listed.total_count
        if total is None and not listed.incomplete:
            total = len(listed.items)
        return ListedItems(
            items=listed.items,
            incomplete=listed.incomplete,
            total_count=total,
        )

    async def list_workflow_runs_for_check_suite(
        self,
        owner: str,
        repo: str,
        check_suite_id: int,
    ) -> ListedItems:
        """List workflow runs for a check suite (every page, not only the first 100)."""

        async def _fetch_page(page: int) -> Any:
            return await self.get(
                f"/repos/{owner}/{repo}/actions/runs",
                params={
                    "check_suite_id": check_suite_id,
                    "per_page": GITHUB_LIST_PAGE_SIZE,
                    "page": page,
                },
            )

        return await paginate_github_list_pages(_fetch_page, item_key="workflow_runs")

    async def list_workflow_run_artifacts(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> ListedItems:
        """List artifacts a workflow run uploaded (every page, not only the first 100)."""

        async def _fetch_page(page: int) -> Any:
            return await self.get(
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts",
                params={"per_page": GITHUB_LIST_PAGE_SIZE, "page": page},
            )

        return await paginate_github_list_pages(_fetch_page, item_key="artifacts")

    async def download_artifact_zip(
        self,
        owner: str,
        repo: str,
        artifact_id: int,
    ) -> bytes:
        """Download one artifact's zip archive, following GitHub's redirect."""
        response = await self._send(
            "GET",
            f"/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip",
            headers={"Accept": DEFAULT_ACCEPT},
            follow_redirects=True,
        )
        return response.content

    async def download_workflow_run_logs(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> bytes:
        """Download one workflow run's log archive, following GitHub's redirect."""
        response = await self._send(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            headers={"Accept": DEFAULT_ACCEPT},
            follow_redirects=True,
        )
        return response.content


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
