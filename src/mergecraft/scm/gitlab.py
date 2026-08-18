"""GitLab ``ScmProvider`` adapter — demand-gated stub (DG9)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

from mergecraft.scm.errors import UnsupportedScmCapability

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmCapability

_PROVIDER = "GitLabScmAdapter"


def _unsupported(capability: str) -> NoReturn:
    raise UnsupportedScmCapability(capability, provider=_PROVIDER)


class GitLabScmAdapter:
    """Second adapter declaring unsupported capabilities instead of emulating GitHub."""

    __slots__ = ("base_url", "token")

    def __init__(self, *, token: str, base_url: str) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    @property
    def capabilities(self) -> frozenset[ScmCapability]:
        return frozenset()

    async def aclose(self) -> None:
        return None

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = (query, variables)
        _unsupported("graphql")

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        _ = (method, path, params, json, headers)
        _unsupported("request")

    async def get(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        _unsupported("get")

    async def post(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        _unsupported("post")

    async def patch(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        _unsupported("patch")

    async def put(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        _unsupported("put")

    async def delete(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        _unsupported("delete")

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        _ = (owner, repo)
        _unsupported("get_repo")

    async def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        _ = (owner, repo, ref)
        _unsupported("get_commit")

    async def get_issue(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, issue_number, kwargs)
        _unsupported("get_issue")

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
        _ = (owner, repo, title, body, labels, extra)
        _unsupported("create_issue")

    async def update_issue(
        self, owner: str, repo: str, issue_number: int, **fields: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, issue_number, fields)
        _unsupported("update_issue")

    async def list_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, issue_number, kwargs)
        _unsupported("list_issue_comments")

    async def get_issue_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, comment_id, kwargs)
        _unsupported("get_issue_comment")

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        _ = (owner, repo, issue_number, body)
        _unsupported("create_issue_comment")

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        _ = (owner, repo, comment_id, body)
        _unsupported("update_issue_comment")

    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        _ = (owner, repo, kwargs)
        _unsupported("list_issues")

    async def create_label(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        color: str = "ededed",
        description: str | None = None,
    ) -> dict[str, Any]:
        _ = (owner, repo, name, color, description)
        _unsupported("create_label")

    async def add_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, issue_number, labels)
        _unsupported("add_labels")

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        _ = (owner, repo, pull_number)
        _unsupported("get_pull")

    async def update_pull(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, pull_number, fields)
        _unsupported("update_pull")

    async def list_pull_files(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, pull_number, kwargs)
        _unsupported("list_pull_files")

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, pull_number, kwargs)
        _unsupported("list_reviews")

    async def get_review(
        self, owner: str, repo: str, pull_number: int, review_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, pull_number, review_id, kwargs)
        _unsupported("get_review")

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, pull_number, fields)
        _unsupported("create_review")

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
        _ = (owner, repo, pull_number, review_id, event, body)
        _unsupported("submit_review")

    async def delete_pending_review(
        self, owner: str, repo: str, pull_number: int, review_id: int
    ) -> dict[str, Any] | None:
        _ = (owner, repo, pull_number, review_id)
        _unsupported("delete_pending_review")

    async def get_review_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, comment_id, kwargs)
        _unsupported("get_review_comment")

    async def create_review_comment_reply(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        _ = (owner, repo, comment_id, body)
        _unsupported("create_review_comment_reply")

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
        _ = (owner, repo, sha, state, context, description, target_url)
        _unsupported("create_status")

    async def list_check_suites_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, ref, kwargs)
        _unsupported("list_check_suites_for_ref")

    async def get_check_suite(self, owner: str, repo: str, check_suite_id: int) -> dict[str, Any]:
        _ = (owner, repo, check_suite_id)
        _unsupported("get_check_suite")

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, ref, kwargs)
        _unsupported("list_check_runs_for_ref")

    async def list_workflow_run_artifacts(
        self, owner: str, repo: str, run_id: int
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, run_id)
        _unsupported("list_workflow_run_artifacts")

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo, artifact_id)
        _unsupported("download_artifact_zip")

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
        _ = (owner, repo, title, head, base, extra)
        _unsupported("create_pull_request")

    async def update_pull_request_body(
        self, owner: str, repo: str, pull_number: int, body: str
    ) -> dict[str, Any]:
        return await self.update_pull(owner, repo, pull_number, description=body)

    async def close_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return await self.update_pull(owner, repo, pull_number, state="closed")

    async def remove_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, issue_number, labels)
        _unsupported("remove_labels")

    async def resolve_review_thread(self, owner: str, repo: str, thread_id: str) -> dict[str, Any]:
        _ = (owner, repo, thread_id)
        _unsupported("resolve_review_thread")
