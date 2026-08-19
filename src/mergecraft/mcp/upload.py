"""upload_file tool — local stub when no upload API is configured."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _check_upload_path(path: Path, resolved_repo_root: str, resolved_tmpdir: str) -> None:
    """Raise ValueError when *path* is a symlink or escapes the allowed roots (#258 / D8).

    A path must be a regular file (not a symlink) and must resolve into the repo
    checkout, a registered cross-repo checkout, or the session tmpdir — the same
    containment rule the git tool and shell cwd use. No file:// URI is emitted
    for a rejected path: the caller raises before reaching URI creation.
    """
    from mergecraft.utils.workspace import WorkspacePathError, confine_to_workspace

    if path.is_symlink():
        msg = f"Blocked: '{path}' is a symlink — symlink escapes are not permitted."
        raise ValueError(msg)
    try:
        confine_to_workspace(str(path), base=resolved_repo_root, extra_roots=(resolved_tmpdir,))
    except WorkspacePathError as exc:
        msg = f"Blocked: '{path}' resolves outside the allowed upload roots — {exc}"
        raise ValueError(msg) from exc


def upload_file_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        path = Path(str(params["path"]))
        resolved_repo_root = str(Path(primary_repo_state(ctx.tool_state).dir).resolve())
        resolved_tmpdir = str(Path(ctx.tmpdir).resolve()) if ctx.tmpdir else ""
        _check_upload_path(path, resolved_repo_root, resolved_tmpdir)
        if not path.is_file():
            msg = f"file not found: {path}"
            raise FileNotFoundError(msg)
        buffer = path.read_bytes()
        if len(buffer) > 10 * 1024 * 1024:
            msg = "file exceeds 10MB limit"
            raise ValueError(msg)
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        api_base = os.environ.get("MERGECRAFT_API_URL", "").rstrip("/")
        if not api_base or not ctx.api_token:
            # Standalone BYOK: copy into tmpdir artifacts and return a file:// URL.
            dest_dir = Path(ctx.tmpdir) / "uploads"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            dest.write_bytes(buffer)
            public_url = dest.as_uri()
            logger.info("stored upload locally at {}", public_url)
            return {
                "success": True,
                "publicUrl": public_url,
                "filename": filename,
                "contentLength": len(buffer),
                "contentType": content_type,
            }

        async with httpx.AsyncClient(timeout=60.0) as client:
            signed = await client.post(
                urljoin(api_base + "/", "api/upload/signed-url"),
                headers={
                    "Authorization": f"Bearer {ctx.api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "filename": filename,
                    "contentType": content_type,
                    "contentLength": len(buffer),
                },
            )
            signed.raise_for_status()
            data = signed.json()
            upload_url = data["uploadUrl"]
            public_url = data["publicUrl"]
            headers = {
                "Content-Type": content_type,
                "Content-Length": str(len(buffer)),
            }
            if data.get("contentDisposition"):
                headers["Content-Disposition"] = data["contentDisposition"]
            put = await client.put(upload_url, content=buffer, headers=headers)
            put.raise_for_status()

        logger.info("uploaded file {}", public_url)
        return {
            "success": True,
            "publicUrl": public_url,
            "filename": filename,
            "contentLength": len(buffer),
            "contentType": content_type,
        }

    return tool(
        name="upload_file",
        tool_class=ToolClass.GITHUB_MUTATION,
        mutates=True,
        description=(
            "Upload a file to get a permanent public URL. Max 10MB. "
            "When embedding images use markdown: ![description](url)"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "absolute path to file to upload"}
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        execute=execute(_run, "upload_file"),
    )
