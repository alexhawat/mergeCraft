"""Minimal Cursor Cloud Agents API v1 client for mergeCraft."""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

CURSOR_API_KEY_ENV = "CURSOR_API_KEY"
_CURSOR_BASE_URL = "https://api.cursor.com"
_DEFAULT_TIMEOUT_S = 120.0
_DEFAULT_MODEL_ID = "composer-2"


def _basic_auth_header(api_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{api_key}:".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _extract_agent_from_create(payload: dict[str, Any]) -> dict[str, Any]:
    agent = payload.get("agent")
    if isinstance(agent, dict) and agent.get("id"):
        return agent
    if payload.get("id"):
        return payload
    msg = "cursor agents.create response missing agent id"
    raise ValueError(msg)


class CursorCloudClient:
    """Async client for Cursor Cloud Agents (``create_cloud_agent``, ``get_run``, ``list_artifacts``)."""

    def __init__(self, *, api_key: str, **kwargs: object) -> None:
        _ = kwargs
        self._api_key = api_key.strip()
        self._agent_id: str | None = None
        self._run_id: str | None = None

    async def _request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{_CURSOR_BASE_URL}{path}"
        headers = {
            **_basic_auth_header(self._api_key),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
        except httpx.HTTPError as exc:
            msg = f"cursor upstream failed: {exc}"
            raise RuntimeError(msg) from exc

        try:
            data = response.json()
        except ValueError as exc:
            msg = f"cursor returned non-JSON (status {response.status_code})"
            raise RuntimeError(msg) from exc

        if not isinstance(data, dict):
            msg = "cursor returned non-object JSON"
            raise RuntimeError(msg)

        if response.status_code >= 400:
            detail = str(data.get("detail") or data.get("message") or data)
            msg = f"cursor API error {response.status_code}: {detail}"
            raise RuntimeError(msg)

        return data

    async def create_cloud_agent(self, **payload: object) -> dict[str, str]:
        """Launch a cloud agent; returns ``id``, ``run_id``, and ``dashboard_url``."""
        prompt = str(payload.get("prompt") or payload.get("prompt_text") or "").strip()
        repo_url = str(payload.get("repo_url") or "").strip()
        starting_ref = str(payload.get("starting_ref") or payload.get("ref") or "main").strip()
        model_raw = payload.get("model")
        model_id = (
            str(model_raw).strip()
            if isinstance(model_raw, str) and model_raw.strip()
            else _DEFAULT_MODEL_ID
        )
        auto_create_pr = bool(payload.get("auto_create_pr", False))
        mcp_servers = payload.get("mcp_servers")

        body: dict[str, Any] = {
            "prompt": {"text": prompt},
            "repos": [{"url": repo_url, "startingRef": starting_ref}],
            "model": {"id": model_id},
            "autoCreatePR": auto_create_pr,
        }
        if isinstance(mcp_servers, list) and mcp_servers:
            body["mcpServers"] = mcp_servers

        data = await self._request(method="POST", path="/v1/agents", json_body=body)
        agent = _extract_agent_from_create(data)
        agent_id = str(agent["id"])
        run = data.get("run")
        run_id = str(run["id"]) if isinstance(run, dict) and run.get("id") else agent_id
        dashboard_url = str(agent.get("url") or f"https://cursor.com/agents/{agent_id}")

        self._agent_id = agent_id
        self._run_id = run_id
        return {
            "id": run_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "dashboard_url": dashboard_url,
        }

    async def get_run(self, run_id: str) -> dict[str, object]:
        """Fetch run status for the agent created by ``create_cloud_agent``."""
        agent_id = self._agent_id or run_id
        path = f"/v1/agents/{agent_id}/runs/{run_id}"
        return await self._request(method="GET", path=path)

    async def list_artifacts(self, run_id: str) -> list[dict[str, str]]:
        """List artifacts for the agent created by ``create_cloud_agent``."""
        agent_id = self._agent_id or run_id
        path = f"/v1/agents/{agent_id}/artifacts"
        data = await self._request(method="GET", path=path)
        items = data.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]


def resolve_cursor_api_key() -> str | None:
    """Return ``CURSOR_API_KEY`` when set."""
    raw = os.environ.get(CURSOR_API_KEY_ENV, "").strip()
    return raw or None


__all__ = ["CURSOR_API_KEY_ENV", "CursorCloudClient", "resolve_cursor_api_key"]
