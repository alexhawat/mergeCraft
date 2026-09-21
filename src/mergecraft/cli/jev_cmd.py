"""``mergecraft jev enable|disable|status|set`` — CLI surface for the Jev gate (#786, #803).

Jev is opt-in and advisory. ``enable`` writes only ``jev.enabled: true`` into
the committed config — every other value keeps coming from ``JevSettings``
defaults so a later change to a threshold or the pinned model reaches every
repo that has not pinned its own value. When ``TYPESAFE_API_KEY`` is not
already set, ``enable`` requests it and writes it to ``.env``; ``--github``
also stores it as the Actions secret when the secret is missing. ``set``
round-trips any single value through ``JevSettings`` before writing, so an
invalid value (a floating model alias, a non-positive budget) is rejected
before the file is touched.

Exports:
    app: Typer subapp registered as ``mergecraft jev``.
    apply_jev_enabled_on_default_branch: ``--github`` PR-opening helper (trust_cmd precedent).
    patch_jev_enabled_yaml: Comment-preserving ``jev.enabled`` patcher.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
from pathlib import Path
from typing import Any

import typer
import yaml
from dotenv import dotenv_values
from loguru import logger
from pydantic import ValidationError

from mergecraft.cli.auth_cmd import _set_gh_secret, _write_env_value
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.interactive import is_interactive_session
from mergecraft.cli.local_env import local_env_path_for_cwd
from mergecraft.cli.provider_cmd import _config_path, _load_config_dict
from mergecraft.cli.trust_cmd import GhRunner, _default_gh_runner, _gh_json, _gh_optional_json
from mergecraft.cli.typer_group import mergecraft_typer
from mergecraft.config.io import append_config_mapping, config_has_yaml_comments, write_config_dict
from mergecraft.config.settings import RepoSettings, load_repo_settings
from mergecraft.jev.client import TYPESAFE_API_KEY_ENV

_JEV_GROUP_HELP = """\
Enable and configure the Jev advisory screening gate.

Jev ranks and annotates review units. It never skips the reviewer, suppresses
a finding, or blocks a merge. A live run also needs TYPESAFE_API_KEY in the
local .env or as a GitHub Actions secret of the same name.

Commands and options

  enable [--cwd PATH] [--github]
      Write jev.enabled: true. No other Jev key is written (defaults stay
      in JevSettings). If TYPESAFE_API_KEY is not already set in the
      environment or .env, prompts for it (hidden) and saves it to .env.
      --cwd PATH     Repository root to update.
      --github       Open a default-branch PR so Actions sees the flag, and
                     store TYPESAFE_API_KEY as a repository secret when a
                     key is available and the secret is missing.

  disable [--cwd PATH] [--github]
      Write jev.enabled: false.
      --cwd PATH     Repository root to update.
      --github       Open a default-branch PR that turns Jev off for Actions.
                     Does not delete the TYPESAFE_API_KEY secret.

  status [--cwd PATH] [--github]
      Show enabled, model, budgetTokens, packs, thresholds, whether
      TYPESAFE_API_KEY is present locally, and the advisory disclaimer.
      --cwd PATH     Repository root to inspect.
      --github       Also report default-branch jev.enabled and whether
                     the TYPESAFE_API_KEY Actions secret is present.

  set KEY VALUE [--cwd PATH]
      Write one Jev parameter after JevSettings validation. Refuses an
      invalid value (floating model alias, non-positive budget) before
      touching the file.
      KEY            enabled, model, budgetTokens, packs.<pack-id>,
                     or thresholds.<name>.
      VALUE          Scalar to write (bool / int / float / str).
      --cwd PATH     Repository root.
"""

app = mergecraft_typer(
    name="jev",
    help=_JEV_GROUP_HELP,
    no_args_is_help=True,
)

_CWD_HELP = "Repository root. Reads and writes .mergecraft/config.yaml here."
_ENABLE_CWD_HELP = (
    "Repository root. Writes jev.enabled in .mergecraft/config.yaml here, "
    "and reads or writes TYPESAFE_API_KEY in .env here."
)
_ENABLE_GITHUB_HELP = (
    "Also prepare GitHub Actions: open a PR against the default branch that "
    "sets jev.enabled: true, and store TYPESAFE_API_KEY as a repository secret "
    "when a key is available and the secret is missing."
)
_DISABLE_GITHUB_HELP = (
    "Also open a PR against the default branch that sets jev.enabled: false "
    "so Actions/PRT see the change. Does not delete the TYPESAFE_API_KEY secret."
)
_STATUS_GITHUB_HELP = (
    "Also report whether the default-branch config has jev.enabled: true and "
    "whether the TYPESAFE_API_KEY Actions secret is present."
)
_SET_KEY_HELP = (
    "Jev key to write: enabled, model, budgetTokens, packs.<pack-id> "
    "(e.g. packs.unit/v1), or thresholds.<name> (e.g. thresholds.unit/v1.likely)."
)
_SET_VALUE_HELP = (
    "Value to write. Booleans (true/false), integers, floats, and strings "
    "are accepted. The value is validated through JevSettings before the file "
    "is touched — a floating model alias or a non-positive budget is refused."
)

_CONFIG_REL = ".mergecraft/config.yaml"
_JEV_HEADER = re.compile(r"^([ \t]*)jev:\s*(?:#.*)?$")
# Any scalar value, not just unquoted lowercase true/false. YAML 1.1 spells a
# boolean as true/True/TRUE/yes/on/... and a consumer may also have quoted it.
# Matching only `true|false` let a valid `enabled: True` fall through to the
# insert path, which appended a second `enabled` key that PyYAML then lost to
# the original — so `disable` reported success while Jev stayed enabled.
_ENABLED_LINE = re.compile(r"^([ \t]+)enabled:[ \t]*([^#\n]*?)[ \t]*((?:#.*)?)$")


def _jev_block_span(lines: list[str]) -> tuple[int, int, int] | None:
    """Return ``(start, end, indent)`` of the ``jev:`` block, or None when absent.

    ``end`` is exclusive and covers the header plus every line that belongs to
    the mapping — deeper-indented entries, and the blank or comment lines
    between them. Trailing blanks are handed back to the caller so a replacement
    does not swallow the separator before the next top-level key.
    """
    for index, line in enumerate(lines):
        header = _JEV_HEADER.match(line)
        if not header:
            continue
        indent = len(header.group(1))
        end = index + 1
        last_content = end
        for offset in range(index + 1, len(lines)):
            candidate = lines[offset]
            stripped = candidate.strip()
            if not stripped:
                end = offset + 1
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent <= indent:
                # A comment at or left of the header's column introduces
                # whatever comes next, so it is not part of this mapping.
                break
            end = offset + 1
            last_content = end
        return index, last_content, indent
    return None


def patch_jev_block_yaml(text: str, block: dict[str, Any]) -> str:
    """Replace the whole ``jev:`` mapping in place, preserving surrounding comments.

    ``append_config_mapping`` appends a second top-level ``jev:`` key, and
    PyYAML keeps the last one — so appending silently discards every Jev
    setting already in the file. This rewrites the existing block instead, and
    only appends when the file has no ``jev:`` mapping at all.
    """
    rendered = yaml.safe_dump({"jev": block}, sort_keys=False, default_flow_style=False)
    lines = text.splitlines(keepends=True)
    span = _jev_block_span(lines)
    if span is None:
        suffix = "" if text.endswith("\n") or not text else "\n"
        return f"{text}{suffix}{rendered}"
    start, end, _ = span
    return "".join(lines[:start]) + rendered + "".join(lines[end:])


def _write_jev_data(path: Path, data: dict[str, Any], *, patch: dict[str, Any]) -> None:
    """Write *patch* into *path*, preserving comments when present (D-comment).

    Never appends a second ``jev:`` key: an appended mapping wins under PyYAML
    and drops every setting the consumer already had.
    """
    if config_has_yaml_comments(path):
        block = patch.get("jev")
        if not isinstance(block, dict):
            append_config_mapping(path, patch)
            return
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        path.write_text(patch_jev_block_yaml(current, block), encoding="utf-8")
        return
    write_config_dict(path, data)


def _reloaded_jev_enabled(path: Path) -> bool | None:
    """Re-read *path* and return what ``jev.enabled`` actually resolves to.

    The write paths are text transforms, so the only trustworthy check that a
    write took effect is parsing the file back the way the loader will.
    """
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    block = loaded.get("jev") if isinstance(loaded, dict) else None
    if not isinstance(block, dict):
        return None
    value = block.get("enabled")
    return value if isinstance(value, bool) else None


def _existing_jev_block(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("jev")
    return dict(raw) if isinstance(raw, dict) else {}


def _validate_jev_block(candidate: dict[str, Any]) -> None:
    """Validate a prospective ``jev:`` block through ``JevSettings`` before writing."""
    try:
        RepoSettings.model_validate({"jev": candidate})
    except ValidationError as exc:
        cli_bail(f"jev config validation failed: {exc}")


def _set_jev_enabled(cwd: Path, *, enabled: bool) -> Path:
    config_path = _config_path(cwd)
    data = _load_config_dict(config_path)
    existing = _existing_jev_block(data)
    # Only the ``enabled`` key changes — every other already-present key is
    # preserved verbatim, and no default is ever written out (D786-1).
    updated = {**existing, "enabled": enabled}
    _validate_jev_block(updated)
    data["jev"] = updated
    if config_has_yaml_comments(config_path) and config_path.is_file():
        # Finer-grained than a block rewrite: flips the one line and keeps
        # every in-block comment the consumer wrote.
        current = config_path.read_text(encoding="utf-8")
        config_path.write_text(patch_jev_enabled_yaml(current, enabled=enabled), encoding="utf-8")
        if _reloaded_jev_enabled(config_path) is not enabled:
            # The line patcher did not take. Never report success on a file
            # that still disagrees: fall back to rewriting the whole mapping,
            # which cannot leave a stale duplicate behind.
            logger.warning("jev enabled patch did not take on {}; rewriting the block", config_path)
            config_path.write_text(
                patch_jev_block_yaml(config_path.read_text(encoding="utf-8"), updated),
                encoding="utf-8",
            )
            if _reloaded_jev_enabled(config_path) is not enabled:
                cli_bail(f"could not set jev.enabled={enabled} in {config_path}")
        return config_path
    _write_jev_data(config_path, data, patch={"jev": updated})
    return config_path


def patch_jev_enabled_yaml(text: str, *, enabled: bool) -> str:
    """Set ``jev.enabled`` under the ``jev:`` block, preserving comments (trust_cmd precedent)."""
    value = "true" if enabled else "false"
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    in_jev = False
    jev_indent = 0
    replaced = False
    out: list[str] = []
    for line in lines:
        header = _JEV_HEADER.match(line)
        if header:
            in_jev = True
            jev_indent = len(header.group(1))
            out.append(line)
            continue
        if in_jev:
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" \t"))
            if stripped and not stripped.startswith("#") and indent <= jev_indent:
                in_jev = False
            elif not replaced:
                match = _ENABLED_LINE.match(line)
                if match and indent > jev_indent:
                    comment = match.group(3) or ""
                    spacer = "  " if comment else ""
                    out.append(f"{match.group(1)}enabled: {value}{spacer}{comment}".rstrip() + "\n")
                    replaced = True
                    continue
        out.append(line)
    if replaced:
        return "".join(out)
    if re.search(r"^jev:\s*(?:#.*)?$", text, flags=re.MULTILINE):
        return re.sub(
            r"^(jev:\s*(?:#.*)?)$",
            rf"\1\n  enabled: {value}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    suffix = "" if text.endswith("\n") or not text else "\n"
    return f"{text}{suffix}jev:\n  enabled: {value}\n"


def apply_jev_enabled_on_default_branch(
    *,
    enabled: bool = True,
    runner: GhRunner | None = None,
) -> str:
    """Open a default-branch PR that sets ``jev.enabled`` for Actions (#786, trust_cmd precedent)."""
    run = runner or _default_gh_runner
    repo_info = _gh_json(run, ["repo", "view", "--json", "nameWithOwner,defaultBranchRef"])
    if not isinstance(repo_info, dict):
        cli_bail("gh repo view returned an unexpected payload")
    repo = str(repo_info.get("nameWithOwner") or "")
    default_ref = repo_info.get("defaultBranchRef")
    default_branch = ""
    if isinstance(default_ref, dict):
        default_branch = str(default_ref.get("name") or "")
    if not repo or not default_branch:
        cli_bail("could not resolve the repository default branch via gh")
    payload = _gh_optional_json(
        run, ["api", f"repos/{repo}/contents/{_CONFIG_REL}?ref={default_branch}"]
    )
    if payload is None:
        cli_bail(
            f"{_CONFIG_REL} does not exist on {default_branch}; "
            f"commit one there before using --github"
        )
    if not isinstance(payload, dict):
        cli_bail(f"could not read default-branch {_CONFIG_REL}")
    content_b64 = str(payload.get("content") or "").replace("\n", "")
    blob_sha = str(payload.get("sha") or "")
    try:
        current = base64.b64decode(content_b64).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        cli_bail(f"could not decode default-branch {_CONFIG_REL}: {exc}")
    updated = patch_jev_enabled_yaml(current, enabled=enabled)
    state = "enable" if enabled else "disable"
    branch = f"mergecraft/jev-{state}"
    existing_branch = _gh_optional_json(run, ["api", f"repos/{repo}/git/ref/heads/{branch}"])
    if updated == current and existing_branch is None:
        cli_bail(f"default-branch {_CONFIG_REL} already has jev.enabled={str(enabled).lower()}")
    if existing_branch is None:
        ref = _gh_json(run, ["api", f"repos/{repo}/git/ref/heads/{default_branch}"])
        head_sha = ""
        if isinstance(ref, dict):
            obj = ref.get("object")
            if isinstance(obj, dict):
                head_sha = str(obj.get("sha") or "")
        if not head_sha:
            cli_bail(f"could not resolve {default_branch} tip SHA")
        _gh_json(
            run,
            ["api", "-X", "POST", f"repos/{repo}/git/refs", "--input", "-"],
            input_text=json.dumps({"ref": f"refs/heads/{branch}", "sha": head_sha}),
        )
    else:
        branch_file = _gh_json(run, ["api", f"repos/{repo}/contents/{_CONFIG_REL}?ref={branch}"])
        if isinstance(branch_file, dict) and branch_file.get("sha"):
            blob_sha = str(branch_file["sha"])
            current_on_branch = ""
            try:
                current_on_branch = base64.b64decode(
                    str(branch_file.get("content") or "").replace("\n", "")
                ).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                current_on_branch = ""
            updated = patch_jev_enabled_yaml(current_on_branch or current, enabled=enabled)
    message = f"chore(jev): set enabled={str(enabled).lower()} on {default_branch} for Actions"
    _gh_json(
        run,
        ["api", "-X", "PUT", f"repos/{repo}/contents/{_CONFIG_REL}", "--input", "-"],
        input_text=json.dumps(
            {
                "message": message,
                "content": base64.b64encode(updated.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "sha": blob_sha,
            }
        ),
    )
    listed = _gh_optional_json(
        run, ["pr", "list", "--repo", repo, "--head", branch, "--json", "url"]
    )
    if isinstance(listed, list) and listed:
        first = listed[0]
        if isinstance(first, dict) and first.get("url"):
            return str(first["url"])
    pr_url = run(
        [
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            default_branch,
            "--head",
            branch,
            "--title",
            message,
            "--body",
            (
                f"Updates default-branch `{_CONFIG_REL}` so the next "
                f"`pull_request_target` run sees `jev.enabled: {str(enabled).lower()}`.\n\n"
                "Jev is advisory only: it ranks and annotates units, it never skips the "
                "reviewer, suppresses a finding, or blocks a merge (see "
                "`docs/jev-gate-patterns.md`'s enforcement-status section). This PR only "
                "writes the committed config.\n\n"
                f"`mergecraft jev enable --github` also stores `{TYPESAFE_API_KEY_ENV}` "
                f"as a repository secret when a key is available and the secret is "
                f"missing. Check with `mergecraft jev status --github`, and if it is "
                f"still missing, set it with `gh secret set {TYPESAFE_API_KEY_ENV} "
                f"--repo {repo}`."
            ),
        ]
    ).strip()
    return pr_url or branch


def _github_secret_present(*, name: str, repo_slug: str) -> bool | None:
    """Return whether *name* is present in *repo_slug*'s Actions secrets, or ``None`` on failure."""
    import subprocess

    try:
        listed = subprocess.run(  # nosec B603 B607 — fixed argv, gh binary
            ["gh", "secret", "list", "--repo", repo_slug, "--json", "name", "-q", ".[].name"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if listed.returncode != 0:
        return None
    return name in listed.stdout.split()


def _default_branch_jev_enabled(*, repo_slug: str) -> bool | None:
    """Return whether the default-branch config has ``jev.enabled: true``, or ``None`` on failure."""
    import subprocess

    try:
        repo_view = subprocess.run(  # nosec B603 B607
            ["gh", "repo", "view", repo_slug, "--json", "defaultBranchRef"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if repo_view.returncode != 0:
        return None
    try:
        default_branch = json.loads(repo_view.stdout)["defaultBranchRef"]["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    try:
        contents = subprocess.run(  # nosec B603 B607
            [
                "gh",
                "api",
                f"repos/{repo_slug}/contents/{_CONFIG_REL}?ref={default_branch}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if contents.returncode != 0:
        return False
    try:
        payload = json.loads(contents.stdout)
        text = base64.b64decode(str(payload.get("content") or "").replace("\n", "")).decode("utf-8")
        loaded = yaml.safe_load(text) or {}
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(loaded, dict):
        return False
    jev_block = loaded.get("jev")
    if not isinstance(jev_block, dict):
        return False
    return bool(jev_block.get("enabled", False))


def _current_repo_slug() -> str | None:
    import subprocess

    try:
        completed = subprocess.run(  # nosec B603 B607
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    slug = completed.stdout.strip()
    return slug or None


def _typesafe_key_from_env_or_file(cwd: Path) -> str | None:
    """Return a non-empty ``TYPESAFE_API_KEY`` from the process env or the repo ``.env``."""
    from_env = os.environ.get(TYPESAFE_API_KEY_ENV, "").strip()
    if from_env:
        return from_env
    env_path = local_env_path_for_cwd(cwd)
    if not env_path.is_file():
        return None
    from_file = (dotenv_values(env_path).get(TYPESAFE_API_KEY_ENV) or "").strip()
    return from_file or None


def _request_typesafe_api_key() -> str | None:
    """Prompt for ``TYPESAFE_API_KEY`` on an interactive session. Never echo the value."""
    if not is_interactive_session():
        return None
    try:
        entered = getpass.getpass(f"{TYPESAFE_API_KEY_ENV} (Enter to skip): ").strip()
    except EOFError:
        return None
    return entered or None


def _save_typesafe_api_key_locally(cwd: Path, key: str) -> Path | None:
    """Write *key* to the repo ``.env``. Return the path on success, else ``None``."""
    env_path = local_env_path_for_cwd(cwd)
    if _write_env_value(env_path, TYPESAFE_API_KEY_ENV, key):
        return env_path
    return None


def _missing_key_note() -> None:
    """Tell the operator how to set ``TYPESAFE_API_KEY`` when enable could not collect it."""
    repo_slug = _current_repo_slug()
    cmd = f"gh secret set {TYPESAFE_API_KEY_ENV}" + (f" --repo {repo_slug}" if repo_slug else "")
    console.print(
        f"[yellow]note:[/yellow] {TYPESAFE_API_KEY_ENV} is not set locally — Jev will "
        f"record a `credential_absent` skip until it is. Set it with:\n  {cmd}"
    )


def _maybe_persist_github_secret(*, key: str | None) -> None:
    """Store ``TYPESAFE_API_KEY`` as an Actions secret when it is missing and *key* is known."""
    repo_slug = _current_repo_slug()
    if repo_slug is None:
        console.print(
            "[yellow]github:[/yellow] could not resolve repository via gh — secret not set"
        )
        return
    present = _github_secret_present(name=TYPESAFE_API_KEY_ENV, repo_slug=repo_slug)
    if present is True:
        console.print(f"{TYPESAFE_API_KEY_ENV} secret on {repo_slug}: already present")
        return
    if not key:
        console.print(
            f"{TYPESAFE_API_KEY_ENV} secret on {repo_slug}: absent — set it with:\n"
            f"  gh secret set {TYPESAFE_API_KEY_ENV} --repo {repo_slug}"
        )
        return
    if _set_gh_secret(name=TYPESAFE_API_KEY_ENV, value=key, repo_slug=repo_slug):
        console.print(f"saved [green]{TYPESAFE_API_KEY_ENV}[/green] Actions secret on {repo_slug}")
        return
    console.print(
        f"[yellow]warning:[/yellow] gh secret set failed — set it with:\n"
        f"  gh secret set {TYPESAFE_API_KEY_ENV} --repo {repo_slug}"
    )


@app.command("enable")
def enable_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help=_ENABLE_CWD_HELP),
    github: bool = typer.Option(False, "--github", help=_ENABLE_GITHUB_HELP),
) -> None:
    """Write ``jev.enabled: true``. Prompt for and save ``TYPESAFE_API_KEY`` when unset.

    No other Jev config key is written. If ``TYPESAFE_API_KEY`` is not already in
    the process env or the repo ``.env``, prompts for it (hidden) and saves it
    to ``.env``. ``--github`` also opens a default-branch PR so Actions sees
    the flag, and stores the key as the ``TYPESAFE_API_KEY`` repository secret
    when a key is available and the secret is missing.
    """
    target = cwd.resolve()
    key = _typesafe_key_from_env_or_file(target)
    if key is None:
        key = _request_typesafe_api_key()
        if key:
            saved = _save_typesafe_api_key_locally(target, key)
            if saved is not None:
                os.environ[TYPESAFE_API_KEY_ENV] = key
                console.print(f"saved [green]{TYPESAFE_API_KEY_ENV}[/green] to {saved}")
            else:
                console.print(
                    f"[yellow]warning:[/yellow] could not write {TYPESAFE_API_KEY_ENV} to .env"
                )
    if github:
        pr_url = apply_jev_enabled_on_default_branch(enabled=True)
        console.print(f"opened default-branch PR for Actions: {pr_url}")
        _maybe_persist_github_secret(key=key)
    config_path = _set_jev_enabled(target, enabled=True)
    console.print(f"wrote [green]{config_path}[/green] jev.enabled=true")
    if not key:
        _missing_key_note()


@app.command("disable")
def disable_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help=_CWD_HELP),
    github: bool = typer.Option(False, "--github", help=_DISABLE_GITHUB_HELP),
) -> None:
    """Write ``jev.enabled: false`` to the committed config.

    ``--github`` opens a default-branch PR so Actions/PRT see the change. It
    does not delete the ``TYPESAFE_API_KEY`` repository secret.
    """
    target = cwd.resolve()
    if github:
        pr_url = apply_jev_enabled_on_default_branch(enabled=False)
        console.print(f"opened default-branch PR for Actions: {pr_url}")
    config_path = _set_jev_enabled(target, enabled=False)
    console.print(f"wrote [green]{config_path}[/green] jev.enabled=false")


def _coerce_jev_value(raw: str) -> Any:
    """Best-effort scalar coercion for ``jev set`` values (bool/int/float/str)."""
    lowered = raw.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


@app.command("set")
def set_cmd(
    key: str = typer.Argument(..., help=_SET_KEY_HELP),
    value: str = typer.Argument(..., help=_SET_VALUE_HELP),
    cwd: Path = typer.Option(Path("."), "--cwd", help=_CWD_HELP),
) -> None:
    """Write one Jev parameter, validated through ``JevSettings`` before writing.

    Allowed keys: ``enabled``, ``model``, ``budgetTokens``, ``packs.<pack-id>``,
    ``thresholds.<name>``. An invalid value is refused before the file is touched.
    """
    target = cwd.resolve()
    config_path = _config_path(target)
    data = _load_config_dict(config_path)
    existing = _existing_jev_block(data)

    top, _, rest = key.strip().partition(".")
    top = top.strip()
    coerced = _coerce_jev_value(value)
    updated = dict(existing)
    if not top:
        cli_bail("provide a jev key, e.g. enabled, model, packs.unit/v1")
    if rest:
        nested_raw = updated.get(top)
        nested = dict(nested_raw) if isinstance(nested_raw, dict) else {}
        nested[rest] = coerced
        updated[top] = nested
    else:
        updated[top] = coerced

    _validate_jev_block(updated)

    data["jev"] = updated
    _write_jev_data(config_path, data, patch={"jev": updated})
    try:
        display = str(config_path.relative_to(target))
    except ValueError:
        display = str(config_path)
    console.print(f"wrote [green]{display}[/green] jev.{key}={value}")


@app.command("status")
def status_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help=_CWD_HELP),
    github: bool = typer.Option(False, "--github", help=_STATUS_GITHUB_HELP),
) -> None:
    """Show config, credential presence, and effective Jev values.

    Prints enabled, model, budgetTokens, packs, thresholds, whether
    TYPESAFE_API_KEY is present locally, and the advisory disclaimer.
    ``--github`` also reports default-branch ``jev.enabled`` and whether the
    Actions secret is present.
    """
    target = cwd.resolve()
    settings = load_repo_settings(root=target, load_learnings_files=False)
    jev = settings.jev
    console.print(f"enabled: {jev.enabled}")
    console.print(f"model: {jev.model}")
    console.print(f"budgetTokens: {jev.budget_tokens}")
    packs = ", ".join(f"{pack}={enabled}" for pack, enabled in sorted(jev.packs.items()))
    console.print(f"packs: {packs}")
    thresholds = ", ".join(f"{name}={value}" for name, value in sorted(jev.thresholds.items()))
    console.print(f"thresholds: {thresholds}")
    has_credential = bool(os.environ.get(TYPESAFE_API_KEY_ENV))
    console.print(f"{TYPESAFE_API_KEY_ENV} present locally: {has_credential}")
    console.print("advisory only — Jev never skips the reviewer or blocks a merge")

    if not github:
        return
    repo_slug = _current_repo_slug()
    if repo_slug is None:
        console.print("[yellow]github:[/yellow] could not resolve repository via gh")
        return
    default_enabled = _default_branch_jev_enabled(repo_slug=repo_slug)
    if default_enabled is None:
        console.print("default-branch jev.enabled: [yellow]unknown (gh lookup failed)[/yellow]")
    else:
        console.print(f"default-branch jev.enabled: {default_enabled}")
    secret_present = _github_secret_present(name=TYPESAFE_API_KEY_ENV, repo_slug=repo_slug)
    if secret_present is None:
        console.print(
            f"{TYPESAFE_API_KEY_ENV} secret on {repo_slug}: [yellow]unknown (gh lookup failed)[/yellow]"
        )
    elif secret_present:
        console.print(f"{TYPESAFE_API_KEY_ENV} secret on {repo_slug}: present")
    else:
        console.print(
            f"{TYPESAFE_API_KEY_ENV} secret on {repo_slug}: absent — set it with:\n"
            f"  gh secret set {TYPESAFE_API_KEY_ENV} --repo {repo_slug}"
        )


__all__ = [
    "app",
    "apply_jev_enabled_on_default_branch",
    "patch_jev_enabled_yaml",
]
