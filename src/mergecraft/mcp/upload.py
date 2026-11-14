"""upload_file tool — local stub when no upload API is configured."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from mergecraft.mcp.shared import ToolClass, ToolRefusedError, execute, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.security.egress import guard_external_url

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec


def _check_upload_path(
    path: Path,
    resolved_repo_root: str,
    resolved_tmpdir: str,
    *,
    checkout_roots: tuple[str, ...] = (),
    run_tmpdir: str = "",
) -> None:
    """Raise ToolRefusedError when *path* may not be uploaded (#258 / D8).

    A path must be a regular file (not a symlink), must not be credential
    material (the same resolve-then-match denylist the git and shell tools
    apply: ``.git/config``, ``.git/credentials``, the askpass tree under the
    session tmpdir and under *run_tmpdir*), and must resolve into the repo checkout, a registered
    cross-repo checkout, or the session tmpdir. No file:// URI is emitted for a
    rejected path: the caller raises before reaching URI creation.
    """
    from mergecraft.utils.path_confinement import ToolPathError, confine_tool_path

    if path.is_symlink():
        msg = f"Blocked: '{path}' is a symlink — symlink escapes are not permitted."
        raise ToolRefusedError(msg)
    try:
        for credentials_tmpdir in dict.fromkeys((resolved_tmpdir, run_tmpdir)):
            confine_tool_path(
                str(path),
                base=resolved_repo_root,
                tmpdir=credentials_tmpdir,
                checkout_roots=(resolved_repo_root, *checkout_roots),
                extra_roots=(resolved_tmpdir,),
            )
    except ToolPathError as exc:
        msg = f"Blocked: '{path}' is not an allowed upload path — {exc}"
        raise ToolRefusedError(msg) from exc


def upload_file_tool(ctx: ToolContext) -> ToolSpec:
    async def _run(params: dict[str, Any]) -> dict[str, bool | str | int]:
        path = Path(str(params["path"]))
        resolved_repo_root = str(Path(primary_repo_state(ctx.tool_state).dir).resolve())
        resolved_tmpdir = str(Path(ctx.tmpdir).resolve()) if ctx.tmpdir else ""
        checkout_roots = tuple(state.dir for state in ctx.tool_state.repos.values())
        _check_upload_path(
            path,
            resolved_repo_root,
            resolved_tmpdir,
            checkout_roots=checkout_roots,
            run_tmpdir=os.environ.get("MERGECRAFT_TEMP_DIR") or "",
        )
        if not path.is_file():
            msg = f"file not found: {path}"
            raise FileNotFoundError(msg)
        buffer = path.read_bytes()
        if len(buffer) > 10 * 1024 * 1024:
            msg = "file exceeds 10MB limit"
            raise ValueError(msg)
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        from mergecraft.config.env import McpEnv

        api_base = (McpEnv().api_url or "").rstrip("/")
        api_token = (ctx.api_token or "").strip()
        if api_base and not api_token:
            msg = "upload_file: missing API token"
            raise ValueError(msg)
        if not api_base:
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

        guard_external_url(api_base if "://" in api_base else f"https://{api_base}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            signed = await client.post(
                urljoin(api_base + "/", "api/upload/signed-url"),
                headers={
                    "Authorization": f"Bearer {api_token}",
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
            guard_external_url(str(upload_url))
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
