"""GitLab ``ScmProvider`` adapter — demand-gated stub (DG9)."""

from __future__ import annotations

from typing import Any

from mergecraft.scm.errors import UnsupportedScmCapability
from mergecraft.scm.protocol import ScmCapability


class GitLabScmAdapter:
    """Second adapter declaring unsupported capabilities instead of emulating GitHub."""

    __slots__ = ("base_url", "token")

    def __init__(self, *, token: str, base_url: str) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    @property
    def capabilities(self) -> frozenset[ScmCapability]:
        return frozenset(
            {
                ScmCapability.CHECK_RUNS,
                ScmCapability.CHECK_SUITES,
                ScmCapability.REVIEW_THREADS,
                ScmCapability.STATUSES,
                ScmCapability.WORKFLOW_ARTIFACTS,
            }
        )

    async def aclose(self) -> None:
        return None

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = (query, variables)
        raise UnsupportedScmCapability("graphql", provider="GitLabScmAdapter")

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
        return {}

    async def get(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        return {}

    async def post(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        return {}

    async def patch(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        return {}

    async def put(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        return {}

    async def delete(self, path: str, **kwargs: Any) -> Any:
        _ = (path, kwargs)
        return None

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return {"full_name": f"{owner}/{repo}"}

    async def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        return {"sha": ref, "project": f"{owner}/{repo}"}

    async def get_issue(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = kwargs
        return {"iid": issue_number, "project": f"{owner}/{repo}"}

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
        _ = (owner, repo, body, labels, extra)
        return {"title": title}

    async def update_issue(
        self, owner: str, repo: str, issue_number: int, **fields: Any
    ) -> dict[str, Any]:
        return {"iid": issue_number, "project": f"{owner}/{repo}", **fields}

    async def list_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, issue_number, kwargs)
        return []

    async def get_issue_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, kwargs)
        return {"id": comment_id}

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        return {"issue": issue_number, "body": body, "project": f"{owner}/{repo}"}

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        return {"id": comment_id, "body": body, "project": f"{owner}/{repo}"}

    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        _ = (owner, repo, kwargs)
        return []

    async def create_label(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        color: str = "ededed",
        description: str | None = None,
    ) -> dict[str, Any]:
        _ = (owner, repo, color, description)
        return {"name": name}

    async def add_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:
        return [
            {"name": label, "issue": issue_number, "project": f"{owner}/{repo}"} for label in labels
        ]

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"iid": pull_number, "project": f"{owner}/{repo}"}

    async def update_pull(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        return {"iid": pull_number, "project": f"{owner}/{repo}", **fields}

    async def list_pull_files(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, pull_number, kwargs)
        return []

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, pull_number, kwargs)
        return []

    async def get_review(
        self, owner: str, repo: str, pull_number: int, review_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, pull_number, kwargs)
        return {"id": review_id}

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **fields: Any
    ) -> dict[str, Any]:
        return {"iid": pull_number, "project": f"{owner}/{repo}", **fields}

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
        return {
            "id": review_id,
            "iid": pull_number,
            "event": event,
            "body": body,
            "project": f"{owner}/{repo}",
        }

    async def delete_pending_review(
        self, owner: str, repo: str, pull_number: int, review_id: int
    ) -> dict[str, Any] | None:
        _ = (owner, repo, pull_number)
        return {"id": review_id}

    async def get_review_comment(
        self, owner: str, repo: str, comment_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        _ = (owner, repo, kwargs)
        return {"id": comment_id}

    async def create_review_comment_reply(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        return {"in_reply_to": comment_id, "body": body, "project": f"{owner}/{repo}"}

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
        return {
            "sha": sha,
            "state": state,
            "context": context,
            "description": description,
            "target_url": target_url,
            "project": f"{owner}/{repo}",
        }

    async def list_check_suites_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        _ = kwargs
        return {"ref": ref, "project": f"{owner}/{repo}", "check_suites": []}

    async def get_check_suite(self, owner: str, repo: str, check_suite_id: int) -> dict[str, Any]:
        return {"id": check_suite_id, "project": f"{owner}/{repo}"}

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        _ = kwargs
        return {"ref": ref, "project": f"{owner}/{repo}", "check_runs": []}

    async def list_workflow_run_artifacts(
        self, owner: str, repo: str, run_id: int
    ) -> list[dict[str, Any]]:
        _ = (owner, repo, run_id)
        return []

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo, artifact_id)
        return b""

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
        return {"title": title, "head": head, "base": base, "project": f"{owner}/{repo}", **extra}

    async def update_pull_request_body(
        self, owner: str, repo: str, pull_number: int, body: str
    ) -> dict[str, Any]:
        return await self.update_pull(owner, repo, pull_number, description=body)

    async def close_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return await self.update_pull(owner, repo, pull_number, state="closed")

    async def remove_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> list[dict[str, Any]]:
        return [{"name": label, "issue": issue_number} for label in labels]

    async def resolve_review_thread(self, owner: str, repo: str, thread_id: str) -> dict[str, Any]:
        _ = (owner, repo)
        return {"threadId": thread_id, "isResolved": True}
