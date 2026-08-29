"""Git invocation guard constants and validators (#299 / D11).

Extracted from ``mcp/git.py`` (was inline at lines 20-315 before this PR).
``mcp/git.py`` re-exports every name from this module so existing
``monkeypatch`` targets keep resolving without modification.

The D11 extract splits the former monolithic ``_SUBCOMMAND_SHORT_FLAGS``
block into the three guard-question tables the issue names:

1. **Which short flags does each subcommand declare?** → ``_SUBCOMMAND_SHORT_FLAGS``
2. **Which subcommands own ``-C`` (so it is not git's chdir)?** → ``_SUBCOMMAND_OWNS_DASH_C``
3. **Which ``--output``-family spellings write a file?** → ``_OUTPUT_FLAG_SPELLINGS``

``_validate_git_invocation`` and the public MCP tool wrappers stay in ``git.py``.

Exports:
    _READONLY_SUBCOMMANDS -- frozenset of allowlisted read-only git subcommands.
    _REDIRECT_TO_TOOL -- dict mapping write verbs to their dedicated tool message.
    _CONFIG_FLAGS -- tuple of the git config-flag spellings (-c, --config-env).
    _BRANCH_READONLY_FLAGS -- frozenset of listing-only branch flags.
    _BRANCH_FLAGS_TAKING_VALUE -- frozenset of branch flags that consume a value arg.
    _SUBCOMMAND_SHORT_FLAGS -- per-subcommand declared short-flag letter sets.
    _SUBCOMMAND_OWNS_DASH_C -- subcommands where -C is their own flag, not git chdir.
    _OUTPUT_FLAG_SPELLINGS -- --output-family spellings that write a file.
    reject_if_leading_dash -- raise if value starts with a dash.
    reject_special_ref -- raise if value is a special/symbolic ref.
    validate_tag_name -- raise if tag contains refspec/flag characters.
    _is_config_flag -- true when token is a git config-flag spelling.
    _subcommand_declares_shorts -- true when subcommand owns every letter in token.
    _reject_config_flags -- raise on config flags or unrecognised short bundles.
    _reject_namespace_flag -- raise on --namespace spellings.
    _reject_no_index -- raise on --no-index spellings.
    _reject_credential_path_operands -- raise on credential-bearing path operands.
    _reject_branch_writes -- raise on branch write flags/positionals.
    _reject_file_writing_flags -- raise on --output-family flags for a subcommand.
"""

from __future__ import annotations

import re
from pathlib import Path

from mergecraft.utils.git_setup import (
    reviewer_askpass_credentials_dir,
    reviewer_denied_relative_paths,
)

# ---------------------------------------------------------------------------
# Q1 — Which subcommands are read-only? (#257 / D7)
# ---------------------------------------------------------------------------

# Read-only subcommand allowlist — everything else is rejected (#257 / D7).
_READONLY_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "rev-parse",
        "describe",
        "ls-files",
        "blame",
        "cat-file",
        "rev-list",
        "branch",
        "show-ref",
        "for-each-ref",
        "ls-remote",
        "config",
    }
)
# Rejected verbs that have a dedicated tool. Not an auth gate — a redirect
# table, consulted before the allowlist so the agent is told where to go rather
# than only that it cannot go here.
_REDIRECT_TO_TOOL: dict[str, str] = {
    "push": "use push_branch instead",
    "fetch": "use git_fetch instead",
    "pull": "use git_fetch then git merge",
    "clone": "use checkout_repo / checkout_pr",
}
# Flags that enable arbitrary code execution via git alias expansion.
# Rejected unconditionally regardless of payload.shell (#257 / D7).
_CONFIG_FLAGS: tuple[str, ...] = ("-c", "--config-env")
# ``branch`` is allowlisted for listing only. Every other flag either writes
# (delete / move / copy / upstream / description edit) or is unknown, so the
# guard is an allowlist rather than a blocklist: a new git release cannot add a
# write flag this tool then forwards.
_BRANCH_READONLY_FLAGS: frozenset[str] = frozenset(
    {
        "-a",
        "-r",
        "-v",
        "-vv",
        "--all",
        "--remotes",
        "--list",
        "--merged",
        "--no-merged",
        "--contains",
        "--no-contains",
        "--points-at",
        "--show-current",
        "--verbose",
        "--sort",
        "--format",
        "--color",
        "--no-color",
        "--column",
        "--no-column",
        "-i",
        "--ignore-case",
    }
)
_BRANCH_FLAGS_TAKING_VALUE: frozenset[str] = frozenset(
    {"--contains", "--no-contains", "--points-at", "--merged", "--no-merged", "--sort", "--format"}
)
# ``config`` is read-only only for lookups. Writes and credential-bearing keys
# stay off the reviewer surface (plan 13 / D12).
_CONFIG_READONLY_FLAGS: frozenset[str] = frozenset({"--get", "--get-all"})
_CONFIG_FLAGS_TAKING_VALUE: frozenset[str] = frozenset({"--get", "--get-all"})

# ---------------------------------------------------------------------------
# Q2 — Which short flags does each allowlisted subcommand declare?
# ---------------------------------------------------------------------------
# Short letters each allowlisted subcommand defines for itself, and the single
# home of that policy. Short flags are subcommand-scoped: ``-c`` is ``--cached``
# to ``ls-files`` and the combined-diff selector to ``log``/``show``, while to
# ``status`` it can only be git's alias-executing config flag. A flat blocklist
# cannot express that, and reading it as one refused real read-only usage
# (``ls-files -co``).
_SUBCOMMAND_SHORT_FLAGS: dict[str, frozenset[str]] = {
    "ls-files": frozenset("cdikmostuvz"),
    "log": frozenset("cmpuz"),
    "show": frozenset("cmpuz"),
    "diff": frozenset("mpuz"),
    # ``branch`` is listing-only here. Bundling is real (``branch -av``) and
    # repetition is meaningful (``-vvv``), so the check is per letter; every
    # write letter — ``d``/``D``/``m``/``M``/``c``/``C`` — is absent, which is
    # what keeps the bundled write forms refused.
    "branch": frozenset("arvi"),
    "show-ref": frozenset("dhns"),
    "for-each-ref": frozenset("cq"),
    "ls-remote": frozenset("ht"),
    "config": frozenset(),
}

# ---------------------------------------------------------------------------
# Q3 — Which subcommands own ``-C`` (not git's chdir)?
# ---------------------------------------------------------------------------
# Subcommands that define ``-C`` themselves, where it is not git's chdir option
# and must not be pulled into the global slot. It means find-copies to ``diff``,
# ``log`` and ``show``, whitespace-insensitive blame to ``blame``, and
# copy-force to ``branch`` — a write, which ``_reject_branch_writes`` refuses on
# its own; what matters here is only that none of them is the chdir option.
_SUBCOMMAND_OWNS_DASH_C: frozenset[str] = frozenset({"diff", "log", "show", "blame", "branch"})

# ---------------------------------------------------------------------------
# Q4 — Which ``--output``-family flags write a file?
# ---------------------------------------------------------------------------
# Flags of an allowlisted read-only subcommand that write a file. The subcommand
# allowlist constrains the verb, not the flags the verb accepts. Every abbreviation
# of ``--output`` git actually resolves is named: ``--out``/``--outp``/``--outpu``
# are ambiguous with the ``--output-indicator-*`` family and git refuses them
# itself, and so are the shorter ``--o``/``--ou``, which is why matching these
# four exactly suffices. ``-o`` is scoped, because it is ``--others`` to
# ``ls-files`` and writes nothing.
_OUTPUT_FLAG_SPELLINGS: frozenset[str] = frozenset({"--out", "--outp", "--outpu", "--output"})

# ---------------------------------------------------------------------------
# Ref-validation helpers
# ---------------------------------------------------------------------------

_SYMBOLIC_REFS: frozenset[str] = frozenset({"HEAD", "FETCH_HEAD", "ORIG_HEAD", "MERGE_HEAD"})
_BAD_REF_CHARS: re.Pattern[str] = re.compile(r"[:+^~?*[\\\s]")


def reject_if_leading_dash(value: str, kind: str) -> None:
    """Raise ``ValueError`` when *value* starts with a dash.

    Args:
        value: The ref or path string to check.
        kind: Human-readable label used in the error message.
    """
    if value.startswith("-"):
        msg = f"Blocked: {kind} '{value}' starts with '-' — git could parse it as a flag."
        raise ValueError(msg)


def reject_special_ref(value: str, kind: str) -> None:
    """Raise ``ValueError`` when *value* is a special or symbolic git ref.

    Args:
        value: The ref string to check.
        kind: Human-readable label used in the error message.
    """
    reject_if_leading_dash(value, kind)
    if value.startswith("refs/"):
        msg = f"Blocked: {kind} '{value}' is a fully-qualified ref path. Use a bare branch name."
        raise ValueError(msg)
    if value in _SYMBOLIC_REFS:
        msg = f"Blocked: {kind} '{value}' is a git symbolic ref, not a branch name."
        raise ValueError(msg)
    match = _BAD_REF_CHARS.search(value)
    if match:
        msg = (
            f"Blocked: {kind} '{value}' contains '{match.group(0)}', which git "
            "interprets as refspec/revision syntax."
        )
        raise ValueError(msg)


def validate_tag_name(tag: str) -> None:
    """Raise ``ValueError`` when *tag* contains refspec or flag characters.

    Args:
        tag: Tag name string to validate.
    """
    reject_if_leading_dash(tag, "tag")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", tag):
        msg = f"Blocked: tag '{tag}' contains characters that could be parsed as a refspec or flag."
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# Config-flag guards
# ---------------------------------------------------------------------------


def _is_config_flag(token: str) -> bool:
    """Whether *token* is a spelling of git's ``-c`` / ``--config-env`` itself.

    Covers the spaced forms (``-c key=value``), the inline long form
    (``--config-env=key=VAR``) and the glued short form (``-ckey=value``) — the
    last identified by the ``=`` a config assignment always carries, since
    ``git -cfoo`` with no value is an error git refuses on its own. ``-C`` is a
    different flag and stays allowed: the comparison is case-sensitive.

    This says nothing about whether the token is *acceptable*: a bare ``-c`` is
    also ``log``'s combined-diff selector, which is what
    ``_subcommand_declares_shorts`` is for.
    """
    if token in _CONFIG_FLAGS or token.startswith("--config-env="):
        return True
    return token.startswith("-c") and len(token) > 2 and "=" in token


def _subcommand_declares_shorts(token: str, subcommand: str) -> bool:
    """Whether *subcommand* defines every short letter bundled in *token*.

    Short flags are subcommand-scoped, so this — not the config-flag test — is
    what tells ``ls-files -co`` and ``log -c`` (read-only invocations) apart from
    ``status -c`` (which can only be git's config flag, misplaced). With no
    subcommand in hand — the pre-subcommand global slot — nothing is declared and
    the strict reading applies.
    """
    known = _SUBCOMMAND_SHORT_FLAGS.get(subcommand, frozenset())
    return all(char in known for char in token[1:])


def _config_flag_message(token: str) -> str:
    return f"Blocked: '{token}' can execute arbitrary code via git alias expansion."


def _bare_dash_c_message(subcommand: str) -> str:
    """Explain a refused bare ``-c`` without claiming the token is the config flag.

    A bare ``-c`` carries no key=value, so nothing in it says whether it is
    git's config flag misplaced after the verb or the subcommand's own short
    flag. The guard refuses it on that ambiguity, not on evidence of an alias
    payload, and the message has to say so: ``git blame -c`` is a real
    read-only invocation and ``git diff -c`` is one git accepts silently.
    """
    forwarded = ", ".join(
        sorted(name for name, shorts in _SUBCOMMAND_SHORT_FLAGS.items() if "c" in shorts)
    )
    return (
        f"Blocked: '{subcommand} -c' — a bare '-c' cannot be told apart from git's own "
        f"config flag at this position, and '{subcommand}' is not recorded as defining "
        f"'-c', so it is refused rather than forwarded. Subcommands whose '-c' is "
        f"forwarded: {forwarded}."
    )


def _reject_config_flags(tokens: list[str], *, subcommand: str = "") -> None:
    """Reject git's config flag, and any ``-c`` token *subcommand* cannot own.

    ``-c`` / ``--config-env`` let an agent inject an alias-expansion shell
    command regardless of ``payload.shell``, and rejection is unconditional —
    there is no safe-key allowlist for ``-c``. Two other ``-c``-shaped tokens
    are refused for their own reasons and with their own messages: a bare
    ``-c`` after a subcommand that does not declare it, which is ambiguous
    rather than proven hostile, and an unrecognised short bundle.

    Raises:
        ValueError: on any of the three refusals.
    """
    for tok in tokens:
        if tok.startswith("--"):
            if _is_config_flag(tok):
                raise ValueError(_config_flag_message(tok))
            continue
        if not tok.startswith("-c") or _subcommand_declares_shorts(tok, subcommand):
            continue
        if tok == "-c" and subcommand:
            raise ValueError(_bare_dash_c_message(subcommand))
        if _is_config_flag(tok):
            raise ValueError(_config_flag_message(tok))
        msg = f"Blocked: '{tok}' bundles short flags {subcommand or 'git'} does not define."
        raise ValueError(msg)


def _reject_namespace_flag(tokens: list[str]) -> None:
    """Raise ValueError if any token is a ``--namespace`` spelling.

    ``--namespace`` sets ``GIT_NAMESPACE``, a ref-namespace prefix rather than a
    filesystem path, so ``confine_to_workspace`` cannot bound it the way it
    bounds ``-C`` / ``--git-dir`` / ``--work-tree``. Only ``upload-pack``,
    ``receive-pack`` and ``upload-archive`` consume it, and none of those is on
    the read-only allowlist, so refusal costs the reviewer no capability while
    keeping the pre-subcommand slot to options this tool can validate.
    """
    for tok in tokens:
        if tok == "--namespace" or tok.startswith("--namespace="):
            msg = (
                f"Blocked: '{tok}' sets a ref namespace the reviewer surface "
                "cannot confine, and no read-only subcommand honours it."
            )
            raise ValueError(msg)


def _no_index_message(token: str) -> str:
    return (
        f"Blocked: '{token}' makes git compare files outside any repository — "
        "the reviewer surface cannot confine paths when --no-index is set, "
        "and no read-only workflow needs it."
    )


def _reject_no_index(tokens: list[str]) -> None:
    """Raise ValueError if any token is a ``--no-index`` spelling (plan 13 / D9).

    ``--no-index`` tells git to diff paths without a repository, which bypasses
    every workspace confinement rule on the operands that follow.
    """
    for tok in tokens:
        if tok == "--no-index" or tok.startswith("--no-index="):
            raise ValueError(_no_index_message(tok))


def _split_end_of_options(args: list[str]) -> tuple[list[str], list[str]]:
    if "--" in args:
        idx = args.index("--")
        return args[:idx], args[idx + 1 :]
    return args, []


def _operands_for_credential_scan(args: list[str]) -> list[str]:
    """Collect subcommand operands that may name a filesystem path."""
    before, after = _split_end_of_options(args)
    operands = list(after)
    for tok in before:
        if tok.startswith("-"):
            continue
        operands.append(tok)
    return operands


def _path_from_git_operand(operand: str) -> str:
    """Extract the file path from a ``rev:path`` operand, or return *operand*."""
    if ":" in operand:
        return operand.split(":", 1)[1]
    return operand


def _path_matches_denied_relative(resolved: Path, denied_rel: str) -> bool:
    denied_parts = Path(denied_rel).parts
    return (
        len(resolved.parts) >= len(denied_parts)
        and resolved.parts[-len(denied_parts) :] == denied_parts
    )


def _resolve_operand_path(path: str, *, cwd: str) -> Path | None:
    candidate = Path(path)
    try:
        if candidate.is_absolute():
            return candidate.resolve()
        return (Path(cwd) / candidate).resolve()
    except OSError:
        return None


def _is_denied_credential_path(path: str, *, cwd: str, tmpdir: str) -> bool:
    resolved = _resolve_operand_path(path, cwd=cwd)
    if resolved is None:
        return False
    for rel in reviewer_denied_relative_paths():
        if _path_matches_denied_relative(resolved, rel):
            return True
    if tmpdir:
        askpass_root = reviewer_askpass_credentials_dir(tmpdir)
        try:
            askpass_resolved = askpass_root.resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(askpass_resolved)
        except ValueError:
            return False
        else:
            return True
    return False


def _credential_path_message(path: str) -> str:
    name = Path(path).name or path
    return (
        f"Blocked: reading '{name}' is not permitted — credential material "
        "must not reach tool output."
    )


def _reject_credential_path_operands(args: list[str], *, cwd: str, tmpdir: str) -> None:
    """Refuse operands that name git credential stores or the askpass tree (D10)."""
    for operand in _operands_for_credential_scan(args):
        path = _path_from_git_operand(operand)
        if _is_denied_credential_path(path, cwd=cwd, tmpdir=tmpdir):
            raise ValueError(_credential_path_message(path))


def shell_command_denies_credential_paths(command: str, *, tmpdir: str) -> str | None:
    """Return a refusal reason when *command* names a denied credential path."""
    for rel in reviewer_denied_relative_paths():
        if rel in command:
            return _credential_path_message(rel)
    if tmpdir:
        askpass_root = reviewer_askpass_credentials_dir(tmpdir)
        askpass_text = str(askpass_root)
        if askpass_text in command or "git-askpass" in command:
            return _credential_path_message("askpass")
    return None


def _is_denied_config_key(key: str) -> bool:
    """Whether a ``git config --get`` key may expose credential material."""
    if key.startswith(("credential.", "url.")):
        return True
    return ".extraHeader" in key


def _config_key_from_get_arg(arg: str, args: list[str], idx: int) -> tuple[str, int]:
    if "=" in arg:
        return arg.split("=", 1)[1], idx + 1
    if idx + 1 < len(args):
        return args[idx + 1], idx + 2
    msg = "Blocked: 'config --get' requires a key."
    raise ValueError(msg)


def _reject_config_invocation(args: list[str]) -> None:
    """Keep ``git config`` to read-only lookups with a credential-key deny-list."""
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if name not in _CONFIG_READONLY_FLAGS:
                if name == "--list":
                    msg = (
                        "Blocked: 'config --list' enumerates all configuration including "
                        "credential material — not permitted on the reviewer surface."
                    )
                    raise ValueError(msg)
                msg = (
                    f"Blocked: 'config {arg}' — only --get and --get-all "
                    "are permitted on the reviewer surface."
                )
                raise ValueError(msg)
            if name == "--get":
                key, idx = _config_key_from_get_arg(arg, args, idx)
                if _is_denied_config_key(key):
                    msg = (
                        f"Blocked: 'config --get {key}' reads credential material — "
                        "not permitted on the reviewer surface."
                    )
                    raise ValueError(msg)
                continue
            if name == "--get-all":
                key, idx = _config_key_from_get_arg(arg, args, idx)
                if _is_denied_config_key(key):
                    msg = (
                        f"Blocked: 'config --get-all {key}' reads credential material — "
                        "not permitted on the reviewer surface."
                    )
                    raise ValueError(msg)
                continue
            idx += 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            msg = (
                f"Blocked: 'config {arg}' — only --get and --get-all "
                "are permitted on the reviewer surface."
            )
            raise ValueError(msg)
        msg = (
            f"Blocked: 'config {arg}' would write configuration — "
            "config writes are not available on the reviewer surface."
        )
        raise ValueError(msg)


def _reject_branch_writes(args: list[str]) -> None:
    """Keep ``git branch`` to listing only (H2, #257 / D7).

    Deletion, rename and copy all write refs, and a rename of the checked-out
    branch changes what ``commit_changes`` / ``push_branch`` later resolve
    through ``rev-parse --abbrev-ref HEAD``. Bare ``git branch <name>`` creates a
    branch, so a positional argument is a write too unless a listing flag that
    takes a value consumed it.
    """
    listing = False
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if name not in _BRANCH_READONLY_FLAGS:
                msg = (
                    f"Blocked: 'branch {arg}' — only listing flags "
                    "are permitted on the reviewer surface."
                )
                raise ValueError(msg)
            listing = listing or name == "--list"
            # A listing flag spelled ``--contains <rev>`` consumes its value, so
            # the value must not be read as a branch name to create.
            if "=" not in arg and name in _BRANCH_FLAGS_TAKING_VALUE:
                idx += 2
                continue
            idx += 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            # Short flags bundle (``-av``) and repeat (``-vvv``), so each letter
            # is checked: one write letter in the bundle refuses the whole token.
            if not _subcommand_declares_shorts(arg, "branch"):
                msg = (
                    f"Blocked: 'branch {arg}' — only listing flags "
                    "are permitted on the reviewer surface."
                )
                raise ValueError(msg)
            idx += 1
            continue
        if listing:
            # In list mode a positional is a glob to match, not a branch to make.
            idx += 1
            continue
        msg = (
            f"Blocked: 'branch {arg}' would create a branch — "
            "branch creation is not available on the reviewer surface."
        )
        raise ValueError(msg)


def _reject_file_writing_flags(command: str, args: list[str]) -> None:
    """Reject flags that make a read-only subcommand write a file (H2).

    ``git diff --output=<path>`` writes wherever it is pointed, so the read-only
    allowlist alone does not make the verb read-only. The four spellings named in
    ``_OUTPUT_FLAG_SPELLINGS`` are compared exactly, which is enough: git resolves
    an option abbreviation only when it is unambiguous, and every shorter form
    (``--o``, ``--ou``) collides with the ``--output-indicator-*`` family, so git
    refuses those before they can write anything. ``-o`` is judged against the
    subcommand: it is ``--others`` to ``ls-files`` and writes nothing there.
    """
    writes_dash_o = "o" not in _SUBCOMMAND_SHORT_FLAGS.get(command, frozenset())
    for arg in args:
        name = arg.split("=", 1)[0]
        if name in _OUTPUT_FLAG_SPELLINGS or (writes_dash_o and name == "-o"):
            msg = f"Blocked: '{command} {arg}' writes a file — the reviewer surface is read-only."
            raise ValueError(msg)


__all__ = [
    "_BAD_REF_CHARS",
    "_BRANCH_FLAGS_TAKING_VALUE",
    "_BRANCH_READONLY_FLAGS",
    "_CONFIG_FLAGS",
    "_CONFIG_FLAGS_TAKING_VALUE",
    "_CONFIG_READONLY_FLAGS",
    "_OUTPUT_FLAG_SPELLINGS",
    "_READONLY_SUBCOMMANDS",
    "_REDIRECT_TO_TOOL",
    "_SUBCOMMAND_OWNS_DASH_C",
    "_SUBCOMMAND_SHORT_FLAGS",
    "_SYMBOLIC_REFS",
    "_bare_dash_c_message",
    "_config_flag_message",
    "_is_config_flag",
    "_is_denied_config_key",
    "_reject_branch_writes",
    "_reject_config_flags",
    "_reject_config_invocation",
    "_reject_credential_path_operands",
    "_reject_file_writing_flags",
    "_reject_namespace_flag",
    "_reject_no_index",
    "_subcommand_declares_shorts",
    "reject_if_leading_dash",
    "reject_special_ref",
    "shell_command_denies_credential_paths",
    "validate_tag_name",
]
