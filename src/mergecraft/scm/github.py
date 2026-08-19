"""GitHub ``ScmProvider`` adapter (DG9)."""

from __future__ import annotations

from typing import Any

from mergecraft.scm.protocol import ScmCapability, ScmProvider
from mergecraft.utils.github import GitHubClient


class GitHubScmAdapter:
    """Wrap ``GitHubClient`` as the first ``ScmProvider`` adapter."""

    __slots__ = ("_client",)

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    @property
    def client(self) -> GitHubClient:
        return self._client

    @property
    def capabilities(self) -> frozenset[ScmCapability]:
        return frozenset(ScmCapability)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await self._client.request(method, path, **kwargs)

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._client.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._client.post(path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self._client.patch(path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self._client.put(path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._client.delete(path, **kwargs)

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._client.graphql(query, variables)

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return await self._client.get_repo(owner, repo)

    async def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        return await self._client.get_commit(owner, repo, ref)

    async def get_issue(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        return await self._client.get_issue(owner, repo, issue_number, **kwargs)

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
        return await self._client.create_issue(
            owner, repo, title=title, body=body, labels=labels, **extra
        )

    async def update_issue(
        self, owner: str, repo: str, issue_number: int, **fields: Any
    ) -> dict[str, Any]:
        return await self._client.update_issue(owner, repo, issue_number, **fields)

    async def list_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return await self._client.list_issue_comments(owner, repo, issue_number, **kwargs)

    async def get_issue_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return await self._client.get_issue_comment(owner, repo, comment_id, **kwargs)

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        return await self._client.create_issue_comment(owner, repo, issue_number, body)

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        return await self._client.update_issue_comment(owner, repo, comment_id, body)

    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        return await self._client.list_issues(owner, repo, **kwargs)

    async def create_label(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        color: str = "ededed",
        description: str | None = None,
    ) -> dict[str, Any]:
        return await self._client.create_label(
            owner, repo, name=name, color=color, description=description
        )

    async def add_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:
        return await self._client.add_labels(owner, repo, issue_number, labels)

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return await self._client.get_pull(owner, repo, pull_number)

    async def update_pull(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        return await self._client.update_pull(owner, repo, pull_number, **fields)

    async def list_pull_files(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return await self._client.list_pull_files(owner, repo, pull_number, **kwargs)

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return await self._client.list_reviews(owner, repo, pull_number, **kwargs)

    async def get_review(
        self, owner: str, repo: str, pull_number: int, review_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return await self._client.get_review(owner, repo, pull_number, review_id, **kwargs)

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        return await self._client.create_review(owner, repo, pull_number, **fields)

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
        return await self._client.submit_review(
            owner, repo, pull_number, review_id, event=event, body=body
        )

    async def delete_pending_review(
        self, owner: str, repo: str, pull_number: int, review_id: int
    ) -> dict[str, Any] | None:
        return await self._client.delete_pending_review(owner, repo, pull_number, review_id)

    async def get_review_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return await self._client.get_review_comment(owner, repo, comment_id, **kwargs)

    async def create_review_comment_reply(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        return await self._client.create_review_comment_reply(owner, repo, comment_id, body)

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
        return await self._client.create_status(
            owner,
            repo,
            sha,
            state=state,
            context=context,
            description=description,
            target_url=target_url,
        )

    async def list_check_suites_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await self._client.list_check_suites_for_ref(owner, repo, ref, **kwargs)

    async def get_check_suite(self, owner: str, repo: str, check_suite_id: int) -> dict[str, Any]:
        return await self._client.get_check_suite(owner, repo, check_suite_id)

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await self._client.list_check_runs_for_ref(owner, repo, ref, **kwargs)

    async def list_workflow_run_artifacts(
        self, owner: str, repo: str, run_id: int
    ) -> list[dict[str, Any]]:
        return await self._client.list_workflow_run_artifacts(owner, repo, run_id)

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        return await self._client.download_artifact_zip(owner, repo, artifact_id)

    # MCP aliases -----------------------------------------------------------

    async def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return await self.get_pull(owner, repo, pull_number)

    async def get_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return await self.list_issue_comments(owner, repo, issue_number, **kwargs)

    async def get_commit_info(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        return await self.get_commit(owner, repo, sha)

    async def list_pull_request_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return await self.list_reviews(owner, repo, pull_number, **kwargs)

    async def list_check_runs(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await self.list_check_suites_for_ref(owner, repo, ref, **kwargs)

    async def edit_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        return await self.update_issue_comment(owner, repo, comment_id, body)

    async def reply_to_review_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        return await self.create_review_comment_reply(owner, repo, comment_id, body)

    async def create_pull_request_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        return await self.create_review(owner, repo, pull_number, **fields)

    async def close_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return await self.update_issue(owner, repo, issue_number, state="closed")

    async def reopen_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return await self.update_issue(owner, repo, issue_number, state="open")

    async def create_pull_request(
        self, owner: str, repo: str, *, title: str, head: str, base: str, **extra: Any
    ) -> dict[str, Any]:
        payload = {"title": title, "head": head, "base": base, **extra}
        result = await self.post(f"/repos/{owner}/{repo}/pulls", json=payload)
        return result if isinstance(result, dict) else {}

    async def update_pull_request_body(
        self, owner: str, repo: str, pull_number: int, body: str
    ) -> dict[str, Any]:
        return await self.update_pull(owner, repo, pull_number, body=body)

    async def close_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return await self.update_pull(owner, repo, pull_number, state="closed")

    async def remove_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:
        removed: list[dict[str, Any]] = []
        for label in labels:
            await self.delete(f"/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}")
            removed.append({"name": label})
        return removed

    async def resolve_review_thread(self, owner: str, repo: str, thread_id: str) -> dict[str, Any]:
        query = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { isResolved }
  }
}
"""
        data = await self.graphql(query, {"threadId": thread_id})
        thread = (data.get("resolveReviewThread") or {}).get("thread") or {}
        return {"isResolved": bool(thread.get("isResolved"))}


def github_client_from_scm(scm: ScmProvider) -> GitHubClient | None:
    """Return the underlying GitHub client when ``scm`` is a GitHub adapter."""
    if isinstance(scm, GitHubScmAdapter):
        return scm.client
    return None


def create_github_scm(token: str, *, client: GitHubClient | None = None) -> GitHubScmAdapter:
    """Build a GitHub adapter from a token or an existing client."""
    return GitHubScmAdapter(client or GitHubClient(token))
