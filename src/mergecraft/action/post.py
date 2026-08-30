"""Codex auth write-back (best-effort post hook).

Without mergecraft.com, refreshed ``CODEX_AUTH_JSON`` is written back via
``gh secret set`` when possible, or logged for manual rotation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

from mergecraft.cli.auth_cmd import _set_gh_secret, _single_line_credential


def _get_state(name: str) -> str:
    # GHA maps saved state into STATE_<name>
    return os.environ.get(f"STATE_{name}", "")


def detect_codex_refresh(*, auth_file_content: str, original_refresh: str) -> str | None:
    """Return refreshed Codex-shaped JSON when the refresh token rotated."""
    try:
        data = json.loads(auth_file_content)
    except json.JSONDecodeError:
        return None

    # OpenCode / Codex auth shapes vary; look for a refresh token field.
    refresh = None
    if isinstance(data, dict):
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
        if isinstance(tokens, dict):
            refresh = tokens.get("refresh_token") or tokens.get("refresh")
        refresh = refresh or data.get("refresh_token") or data.get("refresh")

    if not refresh or refresh == original_refresh:
        return None

    # Prefer returning Codex CLI shape if we can — compact JSON so writeback
    # does not reintroduce multi-line masking (ledger B2).
    if isinstance(data, dict) and "tokens" in data:
        return json.dumps(data)
    return auth_file_content


def _writeback_gh_secret(value: str, repo: str | None = None) -> bool:
    secret_value = _single_line_credential(name="CODEX_AUTH_JSON", value=value)
    return _set_gh_secret(name="CODEX_AUTH_JSON", value=secret_value, repo_slug=repo)


def main() -> None:
    raw = _get_state("codex_writeback")
    if not raw:
        logger.info("codex post-hook: no writeback state — skipping")
        return

    try:
        state = json.loads(raw)
    except json.JSONDecodeError as err:
        logger.warning("codex post-hook: malformed writeback state — {}", err)
        return

    auth_path = state.get("authPath") or state.get("auth_path")
    original_refresh = state.get("originalRefresh") or state.get("original_refresh")
    if not auth_path or not original_refresh:
        logger.warning("codex post-hook: incomplete writeback state — skipping")
        return

    path = Path(auth_path)
    if not path.is_file():
        logger.info("codex post-hook: {} not found — nothing to write back", auth_path)
        return

    try:
        auth_file_content = path.read_text(encoding="utf-8")
    except OSError as err:
        logger.warning("codex post-hook: cannot read {} — {}", auth_path, err)
        return

    refreshed = detect_codex_refresh(
        auth_file_content=auth_file_content,
        original_refresh=original_refresh,
    )
    if not refreshed:
        logger.info("codex post-hook: refresh chain unchanged — no writeback needed")
        return

    repo = os.environ.get("GITHUB_REPOSITORY")
    if _writeback_gh_secret(refreshed, repo=repo):
        logger.info("codex post-hook: refreshed CODEX_AUTH_JSON persisted via gh secret set")
    else:
        logger.warning(
            "codex post-hook: writeback failed — re-run `mergecraft auth codex` when the chain breaks"
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        logger.warning("codex post-hook: unexpected error — {}", err)
