"""Local secret and large-file scanning, with every hook revision frozen.

The ``pre-commit-hooks`` repository already ships ``check-added-large-files``
and ``detect-private-key``; neither is enabled, and the configured revisions
are moving tags. This module pins the end state: the two hooks enabled under
the existing entry, a ``gitleaks`` repository entry present, and every
non-local revision a 40-character SHA carrying its version comment.
"""

from __future__ import annotations

import re
from typing import Any, Final

import yaml

from tests.ci.workflow_support import REPO_ROOT

_PRE_COMMIT: Final = REPO_ROOT / ".pre-commit-config.yaml"
_HOOKS_REPO: Final = "https://github.com/pre-commit/pre-commit-hooks"
_GITLEAKS_REPO: Final = "https://github.com/gitleaks/gitleaks"
_LOCAL_REPO: Final = "local"

# Revision and version comment the plan freezes for the repos that track a
# dev-tool pin (the pydantic-free copy of the rule).
_FROZEN_REVS: Final[dict[str, tuple[str, str]]] = {
    "https://github.com/astral-sh/ruff-pre-commit": (
        "e8f7d69b957a30acb2c875078d5fd012de24b64c",
        "v0.16.7",
    ),
    _HOOKS_REPO: ("cef0300fd0fc4d2a87a85fa2093c6b283ea36f4b", "v5.0.0"),
}

_SHA_REV: Final = re.compile(r"^[0-9a-f]{40}$")


def _config() -> dict[str, Any]:
    loaded = yaml.safe_load(_PRE_COMMIT.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), ".pre-commit-config.yaml did not parse as a mapping"
    return loaded


def _repos() -> list[dict[str, Any]]:
    repos = _config().get("repos") or []
    assert isinstance(repos, list), ".pre-commit-config.yaml repos must be a list"
    return [repo for repo in repos if isinstance(repo, dict)]


def _find(repo_url: str) -> dict[str, Any]:
    for repo in _repos():
        if repo.get("repo") == repo_url:
            return repo
    raise AssertionError(f"no .pre-commit-config.yaml entry for {repo_url}")


def _hook_ids(repo: dict[str, Any]) -> set[str]:
    return {str(hook.get("id")) for hook in repo.get("hooks") or [] if isinstance(hook, dict)}


def test_pre_commit_hooks_are_enabled_for_large_files_and_private_keys() -> None:
    hooks = _hook_ids(_find(_HOOKS_REPO))
    assert "check-added-large-files" in hooks, "the large-file hook is not enabled"
    assert "detect-private-key" in hooks, "the private-key hook is not enabled"

    large_files = next(
        hook
        for hook in _find(_HOOKS_REPO)["hooks"]
        if isinstance(hook, dict) and hook.get("id") == "check-added-large-files"
    )
    assert large_files.get("args") == ["--maxkb=1024"], (
        f"check-added-large-files must cap at 1024 KB, got {large_files.get('args')!r}"
    )


def test_gitleaks_hook_is_present_and_sha_pinned() -> None:
    repo = _find(_GITLEAKS_REPO)
    assert "gitleaks" in _hook_ids(repo), f"gitleaks repo has no gitleaks hook: {repo}"
    rev = str(repo.get("rev", ""))
    assert _SHA_REV.fullmatch(rev), f"gitleaks rev must be a 40-character SHA, got {rev!r}"


def test_every_non_local_rev_is_a_sha_with_a_version_comment() -> None:
    raw = _PRE_COMMIT.read_text(encoding="utf-8")
    for repo in _repos():
        url = str(repo.get("repo", ""))
        if url == _LOCAL_REPO:
            continue
        rev = str(repo.get("rev", ""))
        assert _SHA_REV.fullmatch(rev), f"{url} rev must be a 40-character SHA, got {rev!r}"
        line = re.search(rf"^\s*rev:\s*{re.escape(rev)}\b.*$", raw, re.MULTILINE)
        assert line is not None, f"cannot find the raw rev line for {url}"
        assert re.search(r"#\s*v[0-9]", line.group(0)), (
            f"{url} rev must carry a `# v<version>` comment: {line.group(0).strip()!r}"
        )


def test_pin_tracking_repos_are_frozen_to_known_shas() -> None:
    for url, (sha, version) in _FROZEN_REVS.items():
        repo = _find(url)
        assert repo.get("rev") == sha, f"{url} must freeze to {sha}, got {repo.get('rev')!r}"
        raw = _PRE_COMMIT.read_text(encoding="utf-8")
        assert re.search(rf"^\s*rev:\s*{sha}\b.*#\s*{re.escape(version)}\b", raw, re.MULTILINE), (
            f"{url} must carry the `# {version}` comment beside its SHA"
        )
