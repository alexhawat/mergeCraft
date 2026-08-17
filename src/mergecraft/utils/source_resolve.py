"""Bounded, credential-safe acquisition of third-party review sources (TS3)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger

from mergecraft.mcp.git import _git_env
from mergecraft.utils.workspace import register_workspace_root

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import TrustTier

ALLOWED_SCHEMES = frozenset({"https"})
ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})

DEFAULT_MAX_BYTES = 500 * 1024 * 1024
DEFAULT_MAX_FILES = 50_000
DEFAULT_DEPTH = 1

_LOCAL_BARE_RE = re.compile(r"\.git$")


class SourceResolveError(ValueError):
    """Base error for source acquisition policy violations."""


class CloneUrlError(SourceResolveError):
    """Raised when a clone URL fails scheme or host policy."""


class CloneAuthError(SourceResolveError):
    """Raised when authentication is required or rejected (D10)."""


class CloneLimitError(SourceResolveError):
    """Raised when a clone exceeds configured size or file-count ceilings."""


@dataclass(frozen=True, slots=True)
class ReviewSource:
    """Remote acquisition descriptor for a third-party tree (TS3)."""

    url: str
    ref: str = "main"
    token: str | None = None
    depth: int = DEFAULT_DEPTH


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    """A bounded tree ready for offline review."""

    path: Path
    workspace_root: Path


def validate_clone_url(url: str) -> None:
    """Reject disallowed schemes, embedded credentials, and non-allowlisted hosts."""
    if _LOCAL_BARE_RE.search(url) and Path(url).exists():
        return
    if url.startswith("git@"):
        msg = "ssh transport is not allowed for third-party clone acquisition"
        raise CloneUrlError(msg)
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme == "ssh":
        msg = "ssh transport is not allowed for third-party clone acquisition"
        raise CloneUrlError(msg)
    if scheme and scheme not in ALLOWED_SCHEMES:
        msg = f"unsupported URL scheme: {scheme!r}"
        raise CloneUrlError(msg)
    if parsed.username or parsed.password:
        msg = "embedded credentials in clone URL are not allowed"
        raise CloneUrlError(msg)
    host = (parsed.hostname or "").lower()
    if host and host not in ALLOWED_HOSTS:
        msg = f"host not allowlisted: {host!r}"
        raise CloneUrlError(msg)


def _run_git(args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        if (
            "Authentication failed" in err
            or "could not read Username" in err
            or "could not read from remote repository" in err
            or "Repository not found" in err
            or "not found" in err.lower()
            or "401" in err
            or "403" in err
            or "404" in err
        ):
            raise CloneAuthError(
                "authentication required for private repository — pass --token, "
                "set GH_TOKEN/GITHUB_TOKEN, or run `gh auth login`"
            )
        msg = f"git {' '.join(args)} failed ({result.returncode}): {err}"
        raise RuntimeError(msg)
    return result.stdout


def _credential_env(token: str | None) -> dict[str, str]:
    """Build git environment with header-based auth — never URL-embedded (D5)."""
    env = _git_env(token or "")
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _redirect_hardening_args() -> list[str]:
    return ["-c", "http.followRedirects=false"]


def _scrub_clone_credentials(repo_dir: Path) -> None:
    """Remove any credential material from the local git config after fetch (D5)."""
    for key in (
        "http.extraHeader",
        "credential.helper",
        "credential.username",
        "credential.useHttpPath",
    ):
        subprocess.run(
            ["git", "config", "--local", "--unset-all", key],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    config_path = repo_dir / ".git" / "config"
    if not config_path.is_file():
        return
    text = config_path.read_text(encoding="utf-8")
    scrubbed = re.sub(
        r"(?im)^\s*extraHeader\s*=.*authorization:.*$",
        "",
        text,
    )
    if scrubbed != text:
        config_path.write_text(scrubbed, encoding="utf-8")


def _tree_stats(root: Path) -> tuple[int, int]:
    total_bytes = 0
    file_count = 0
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            file_count += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
    return total_bytes, file_count


def _enforce_limits(root: Path, *, max_bytes: int, max_files: int) -> None:
    total_bytes, file_count = _tree_stats(root)
    if total_bytes > max_bytes:
        msg = f"clone size {total_bytes} bytes exceeds ceiling {max_bytes}"
        raise CloneLimitError(msg)
    if file_count > max_files:
        msg = f"clone file count {file_count} exceeds ceiling {max_files}"
        raise CloneLimitError(msg)


def _sanitize_remote_url(url: str) -> str:
    """Return a credential-free remote URL for ``git remote add``."""
    validate_clone_url(url)
    if _LOCAL_BARE_RE.search(url) and Path(url).exists():
        return url
    parsed = urlparse(url)
    host = parsed.hostname or "github.com"
    path = parsed.path or ""
    if not path.endswith(".git"):
        path = f"{path.rstrip('/')}.git"
    return f"https://{host}{path}"


def acquire(
    source: ReviewSource,
    *,
    dest: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> AcquiredSource:
    """Acquire a foreign repository with URL, credential, and size policy (TS3)."""
    validate_clone_url(source.url)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    remote_url = _sanitize_remote_url(source.url)
    depth = max(1, min(source.depth, 50))
    env = _credential_env(source.token)
    redirect_args = _redirect_hardening_args()

    try:
        _run_git(["init", "-q"], cwd=str(dest))
        _run_git(["remote", "add", "origin", remote_url], cwd=str(dest))
        fetch_args = [
            *redirect_args,
            "fetch",
            "--depth",
            str(depth),
            "--no-tags",
            "--no-recurse-submodules",
            "origin",
            source.ref,
        ]
        _run_git(fetch_args, cwd=str(dest), env=env)
        _run_git(["checkout", "-B", source.ref, "FETCH_HEAD"], cwd=str(dest))
    except (RuntimeError, CloneAuthError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        err = str(exc)
        if source.token is None and (
            isinstance(exc, CloneAuthError)
            or "Authentication failed" in err
            or "could not read Username" in err
            or "could not read from remote repository" in err
            or "Repository not found" in err
            or "not found" in err.lower()
            or "401" in err
            or "403" in err
            or "404" in err
        ):
            raise CloneAuthError(
                "authentication required for private repository — pass --token, "
                "set GH_TOKEN/GITHUB_TOKEN, or run `gh auth login`"
            ) from exc
        raise
    finally:
        if dest.exists():
            _scrub_clone_credentials(dest)

    try:
        _enforce_limits(dest, max_bytes=max_bytes, max_files=max_files)
    except CloneLimitError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    workspace_root = dest.resolve()
    register_workspace_root(str(workspace_root))
    logger.info("acquired review source at {} (ref={})", workspace_root, source.ref)
    return AcquiredSource(path=workspace_root, workspace_root=workspace_root)


def confine_path(workspace_root: Path, relative_path: str | Path) -> Path | None:
    """Resolve ``relative_path`` inside ``workspace_root``; drop escapes (D7)."""
    root = workspace_root.resolve()
    candidate = Path(relative_path)
    try:
        resolved = (
            (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        )
        resolved.relative_to(root)
    except OSError, ValueError:
        logger.info("dropped path outside workspace: {}", relative_path)
        return None
    if resolved.is_symlink():
        try:
            target = resolved.resolve()
            target.relative_to(root)
        except OSError, ValueError:
            logger.info("dropped symlink escaping workspace: {}", relative_path)
            return None
    return resolved


def filter_confined_paths(workspace_root: Path, paths: list[str]) -> list[str]:
    """Keep only diff paths that remain inside the workspace root (D7)."""
    kept: list[str] = []
    for raw in paths:
        confined = confine_path(workspace_root, raw)
        if confined is None:
            continue
        try:
            confined.relative_to(workspace_root.resolve())
        except ValueError:
            continue
        kept.append(raw)
    return kept


def cli_analyzer_sandbox_applies(*, trust_tier: TrustTier | str, repo_root: Path) -> bool:
    """Return whether the offline CLI path applies analyzer sandbox policy."""
    from mergecraft.analyzers.manifest import load_manifest_file
    from mergecraft.analyzers.sandbox import plan_sandbox

    if trust_tier != "untrusted":
        return False
    manifest = load_manifest_file(Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml"))
    plan_sandbox(
        manifest=manifest,
        tier="untrusted",
        repo_root=repo_root,
        scratch_dir=repo_root / ".mergecraft-scratch",
    )
    return True


__all__ = [
    "DEFAULT_DEPTH",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "AcquiredSource",
    "CloneAuthError",
    "CloneLimitError",
    "CloneUrlError",
    "ReviewSource",
    "SourceResolveError",
    "acquire",
    "cli_analyzer_sandbox_applies",
    "confine_path",
    "filter_confined_paths",
    "validate_clone_url",
]
