"""Bounded, credential-safe acquisition and resolution of review sources (TS3/TS4)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from loguru import logger

from mergecraft.utils.git_setup import git_env_for_token, scrub_clone_credentials
from mergecraft.utils.offline_diff import DiffMaterialization, materialize_diff
from mergecraft.utils.workspace import register_workspace_root

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import TrustTier

ALLOWED_SCHEMES = frozenset({"https"})
ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})

DEFAULT_MAX_BYTES = 500 * 1024 * 1024
DEFAULT_MAX_FILES = 50_000
DEFAULT_DEPTH = 1

_LOCAL_BARE_RE = re.compile(r"\.git$")
_OWNER_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_COMMIT_RANGE_RE = re.compile(r"^[\w./^~@{}_-]+\.\.[\w./^~@{}_-]+$")


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
    return git_env_for_token(token or "")


def _redirect_hardening_args() -> list[str]:
    return ["-c", "http.followRedirects=false"]


def _scrub_clone_credentials(repo_dir: Path) -> None:
    scrub_clone_credentials(repo_dir)


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


@dataclass(frozen=True, slots=True)
class AuthResolution:
    """Resolved GitHub credential for clone acquisition (D10)."""

    token: str | None
    source: str


@dataclass(frozen=True, slots=True)
class SourceResolverSpec:
    """CLI flags that describe which tree and diff to review (TS4)."""

    repo: str | None = None
    head: str | None = None
    base: str | None = None
    staged: bool = False
    unstaged: bool = False
    commit_range: str | None = None
    token: str | None = None
    cwd: Path = field(default_factory=Path.cwd)
    invocation_root: Path = field(default_factory=Path.cwd)


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """A review workspace after source resolution."""

    cwd: Path
    git_common_dir: Path | None
    cloned: bool
    temp_dir: Path | None = None


def resolve_auth_token(*, explicit: str | None = None) -> AuthResolution:
    """Resolve GitHub auth with D10 precedence."""
    if explicit:
        return AuthResolution(token=explicit, source="--token")
    for env_var in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(env_var)
        if value:
            return AuthResolution(token=value, source=env_var)
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        token = result.stdout.strip()
        if token:
            return AuthResolution(token=token, source="gh auth token")
    return AuthResolution(token=None, source="anonymous")


def parse_commit_range(range_str: str) -> tuple[str, str]:
    """Validate and split a ``left..right`` commit range."""
    cleaned = range_str.strip()
    if not _COMMIT_RANGE_RE.match(cleaned):
        msg = f"malformed commit range: {range_str!r}"
        raise ValueError(msg)
    if any(char in cleaned for char in (";", "|", "&", "$", "`")):
        msg = f"malformed commit range: {range_str!r}"
        raise ValueError(msg)
    left, right = cleaned.split("..", 1)
    return left, right


def resolve_git_common_dir(cwd: Path) -> Path | None:
    """Return the resolved git common directory for linked worktrees (D9)."""
    git_entry = cwd / ".git"
    if not git_entry.exists():
        return None
    try:
        output = _run_git(["rev-parse", "--git-common-dir"], cwd=str(cwd.resolve()))
    except RuntimeError:
        return None
    common = (cwd / output.strip()).resolve()
    return common if common.is_dir() else None


def _normalize_remote_repo(repo: str) -> str:
    candidate = repo.strip()
    if _OWNER_REPO_RE.match(candidate):
        owner, name = candidate.split("/", 1)
        return f"https://github.com/{owner}/{name}.git"
    if candidate.startswith("file://"):
        parsed = urlparse(candidate)
        return str(Path(unquote(parsed.path)).resolve())
    if candidate.startswith(("https://", "http://")):
        return candidate
    path = Path(candidate)
    if path.exists():
        return str(path.resolve())
    msg = f"unrecognized repository source: {repo!r}"
    raise SourceResolveError(msg)


def _is_remote_source(repo: str) -> bool:
    candidate = repo.strip()
    if candidate.startswith("file://"):
        return True
    if _OWNER_REPO_RE.match(candidate):
        return True
    if candidate.startswith(("https://", "http://")):
        return True
    parsed = urlparse(candidate)
    return bool(parsed.scheme)


def resolve_workspace(spec: SourceResolverSpec) -> ResolvedWorkspace:
    """Resolve ``--repo`` / ``--cwd`` into a review workspace."""
    if spec.repo is None:
        cwd = spec.cwd.resolve()
        return ResolvedWorkspace(
            cwd=cwd,
            git_common_dir=resolve_git_common_dir(cwd),
            cloned=False,
        )

    repo = spec.repo.strip()
    if _is_remote_source(repo):
        auth = resolve_auth_token(explicit=spec.token)
        url = _normalize_remote_repo(repo)
        ref = spec.head or "main"
        temp_dir = Path(tempfile.mkdtemp(prefix="mergecraft-source-"))
        acquired = acquire(
            ReviewSource(url=url, ref=ref, token=auth.token),
            dest=temp_dir,
        )
        if spec.base and spec.base != ref:
            redirect_args = _redirect_hardening_args()
            _run_git(
                [
                    *redirect_args,
                    "fetch",
                    "--depth",
                    str(DEFAULT_DEPTH),
                    "--no-tags",
                    "origin",
                    f"{spec.base}:refs/remotes/origin/{spec.base}",
                ],
                cwd=str(acquired.path),
                env=_credential_env(auth.token),
            )
        return ResolvedWorkspace(
            cwd=acquired.path,
            git_common_dir=resolve_git_common_dir(acquired.path),
            cloned=True,
            temp_dir=temp_dir,
        )

    local = Path(repo).expanduser().resolve()
    if not local.exists():
        msg = f"repository path does not exist: {local}"
        raise SourceResolveError(msg)
    return ResolvedWorkspace(
        cwd=local,
        git_common_dir=resolve_git_common_dir(local),
        cloned=False,
    )


def materialize_resolved_diff(
    workspace: ResolvedWorkspace,
    *,
    spec: SourceResolverSpec,
    out_dir: Path,
    diff_file: Path | None = None,
) -> DiffMaterialization:
    """Materialize a diff for a resolved workspace (TS4)."""
    from mergecraft.utils.offline_diff import (
        git_range_diff,
        git_ref_diff,
        git_staged_diff,
        git_unstaged_diff,
    )

    if diff_file is not None:
        return materialize_diff(
            cwd=workspace.cwd,
            out_dir=out_dir,
            diff_file=diff_file,
            git_dir=workspace.git_common_dir,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "review.diff"
    base_ref: str | None = None

    if spec.staged:
        text = git_staged_diff(cwd=workspace.cwd)
        base_ref = None
    elif spec.unstaged:
        text = git_unstaged_diff(cwd=workspace.cwd)
        base_ref = None
    elif spec.commit_range:
        parse_commit_range(spec.commit_range)
        text = git_range_diff(cwd=workspace.cwd, range_spec=spec.commit_range)
        base_ref = spec.commit_range
    elif spec.head or spec.base:
        base_ref = spec.base or "main"
        head = "HEAD" if workspace.cloned and spec.head else (spec.head or "HEAD")
        text = git_ref_diff(
            cwd=workspace.cwd,
            base=base_ref,
            head=head,
            git_dir=workspace.git_common_dir,
        )
    else:
        return materialize_diff(
            cwd=workspace.cwd,
            out_dir=out_dir,
            base=spec.base,
            git_dir=workspace.git_common_dir,
        )

    if text and not text.endswith("\n"):
        text = f"{text}\n"
    path.write_text(text, encoding="utf-8")
    line_count = 0 if not text.strip() else text.count("\n")
    empty = not text.strip()
    logger.info(
        "» offline diff ready ({} lines{}) → {}",
        line_count,
        f", base={base_ref}" if base_ref else "",
        path,
    )
    return DiffMaterialization(path=path, base_ref=base_ref, line_count=line_count, empty=empty)


__all__ = [
    "DEFAULT_DEPTH",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "AcquiredSource",
    "AuthResolution",
    "CloneAuthError",
    "CloneLimitError",
    "CloneUrlError",
    "ResolvedWorkspace",
    "ReviewSource",
    "SourceResolveError",
    "SourceResolverSpec",
    "acquire",
    "cli_analyzer_sandbox_applies",
    "confine_path",
    "filter_confined_paths",
    "materialize_resolved_diff",
    "parse_commit_range",
    "resolve_auth_token",
    "resolve_git_common_dir",
    "resolve_workspace",
    "validate_clone_url",
]
