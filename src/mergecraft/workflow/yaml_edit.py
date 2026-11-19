"""Comment-preserving workflow YAML location and mutation helpers.

PyYAML parses workflow structure and validates the edited result; line-based
edits preserve comments, quoting, and unrelated YAML. Callers supply owned
keys and semantic checks for their wiring operation.

Module: mergecraft.workflow.yaml_edit
Depends: yaml

Exports:
    ACTION_USES, DEFAULT_WORKFLOW_RELATIVE_PATH -- action and workflow defaults.
    LogfireWorkflowError, WorkflowYamlError -- shared mutation error aliases.
    WiringChange, WorkflowChange -- shared mutation result aliases.
    is_action_uses -- match the action name and a non-empty reference.
    line_indent_len, derive_child_indent -- inspect existing indentation.
    find_action_steps, step_identifier, parsed_step_identifiers -- locate steps.
    select_step_indices -- resolve primary, all, or named step selectors.
    find_mapping_block -- locate a mapping at the requested indentation.
    splice_secret -- validate an Actions secret or variable identifier.
    insert_owned_keys_into_block -- insert or replace caller-owned keys.
    mutate_steps -- edit selected steps and run semantic checks.
    ensure_yaml_loadable -- validate edited YAML syntax.
    create_with_block, create_env_block -- create missing step mappings.
    render_workflow_diff -- render a bounded unified diff.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable  # noqa: TC003 -- preserve runtime annotation resolution
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 -- preserve runtime annotation resolution

import yaml

DEFAULT_WORKFLOW_RELATIVE_PATH = ".github/workflows/mergecraft.yml"
ACTION_USES = "alexhawat/mergeCraft"


def is_action_uses(uses: str, action_uses: str = ACTION_USES) -> bool:
    """Return ``True`` iff ``uses`` is the action followed by ``@<ref>``.

    Owner and repo names are case-insensitive per GitHub, so the owner/repo
    part is compared case-insensitively: ``alexhawat/mergecraft@<sha>`` (the
    spelling the docs print) matches the canonical ``alexhawat/mergeCraft``.
    The ``@`` is mandatory and the reference after it must be non-empty --
    a bare ``startswith`` would also match ``alexhawat/mergeCraft-fork``,
    ``alexhawat/mergecraftx`` and similar forks, and silently wire the
    Logfire token into an action we do not own.
    """
    prefix = action_uses + "@"
    if uses[: len(prefix)].casefold() != prefix.casefold():
        return False
    return bool(uses[len(prefix) :])


class LogfireWorkflowError(Exception):
    """Raised when the workflow mutator cannot proceed safely."""


@dataclass
class WiringChange:
    """Result of a wire / unwire mutation.

    ``old_text`` / ``new_text`` carry the full file content before / after
    the mutation. ``was_modified`` is ``True`` iff the two differ (the CLI
    uses this to decide between printing a diff and printing "already
    wired, no changes needed"). ``affected_steps`` lists the ``id:`` or
    ``name:`` of every step the mutation touched.
    """

    old_text: str
    new_text: str
    affected_steps: list[str] = field(default_factory=list)

    @property
    def was_modified(self) -> bool:
        return self.old_text != self.new_text


def line_indent_len(line: str) -> int:
    """Return the indent (in characters) of ``line``. Blank lines return 0."""
    if not line.strip():
        return 0
    return len(line) - len(line.lstrip(" \t"))


def derive_child_indent(
    block_text: str, block_start: int, block_end: int, key_indent: int
) -> str | None:
    """Return the canonical child-indent string for a mapping block.

    The block is delimited by ``[block_start, block_end)`` inside ``block_text``
    and is expected to contain a ``key:`` line whose indent is ``key_indent``
    followed (or not) by child lines. Returns the whitespace prefix of the
    first child line whose indent is strictly deeper than ``key_indent``, or
    ``None`` if no such line exists.

    This is the single source of truth used by both the insert path and the
    strip / create-env paths so that the wire and unwire operations agree on
    indentation on workflows that use a non-canonical (e.g. 4-space) child
    indent. Previously the strip / create paths hardcoded ``key_indent + 2``,
    which made wire -> unwire round trips silently no-op on such files: the
    wire would insert at the dynamic +6 indent, the unwire would only scan
    for owned keys at the hardcoded +2 indent, and the keys would remain.
    """
    lines = block_text[block_start:block_end].splitlines(keepends=True)
    for ln in lines[1:]:
        if not ln.strip():
            continue
        leading = line_indent_len(ln)
        if leading <= key_indent:
            break
        return ln[:leading]
    return None


def find_action_steps(text: str, action_uses: str = ACTION_USES) -> list[tuple[int, int, int]]:
    """Locate every ``uses: <action_uses>`` step in ``text``.

    Returns a list of ``(step_start, step_end, step_indent_len)`` tuples.
    ``step_start`` is the byte offset of the line containing the leading ``-``
    list marker; ``step_end`` is the byte offset of the first line at the
    same or shallower indent, or end of file. ``step_indent_len`` is the
    number of leading whitespace characters on the leading ``-`` line.
    """
    lines = text.splitlines(keepends=True)
    out: list[tuple[int, int, int]] = []
    # Require ``@`` immediately after the action name. ``\b`` would also
    # match ``alexhawat/mergeCraft-fork``, ``alexhawat/mergecraftx``, etc. --
    # a fork that we must not wire the Logfire token into. Owner/repo names
    # are case-insensitive, hence ``re.IGNORECASE`` so the lowercase docs
    # spelling matches too.
    # Match both step shapes documented by the README:
    #   - multi-line form: ``- name: foo`` then ``  uses: alexhawat/mergeCraft@X``
    #   - inline form:     ``- uses: alexhawat/mergeCraft@X``
    # ``ws`` captures any leading whitespace; then the body indent is the
    # whitespace between ``-`` and ``uses:`` (inline) or between line
    # start and ``uses:`` (multi-line). ``inline_ws`` / ``multiline_ws``
    # are mutually exclusive -- exactly one is set on a successful match.
    uses_re = re.compile(
        r"^(?P<ws>[ \t]*)"
        r"(?:-(?P<inline>[ \t]+)|(?P<multiline>[ \t]+))"
        r"uses:[ \t]*" + re.escape(action_uses) + r"@(?=\S)",
        re.IGNORECASE,
    )
    cum: list[int] = []
    offset = 0
    for ln in lines:
        cum.append(offset)
        offset += len(ln)
    total = offset

    for i, line in enumerate(lines):
        m = uses_re.match(line)
        if m is None:
            continue
        ws = m.group("ws")
        # The body indent of the step -- the column ``with:`` / ``env:``
        # siblings live at -- is the column of ``uses:`` itself (the
        # siblings are written underneath at the same column).
        #   - Multi-line form: ``ws`` + ``multiline`` holds all leading
        #     whitespace before ``uses:``, so ``step_indent = len(ws) +
        #     len(multiline)``.
        #   - Inline form: ``ws`` holds the indent before ``-``,
        #     ``inline`` holds the whitespace between ``-`` and
        #     ``uses:``; ``uses:`` itself sits at column
        #     ``len(ws) + 1 + len(inline)`` (one for the ``-`` plus the
        #     whitespace consumed by ``inline``).
        inline_ws = m.group("inline")
        multiline_ws = m.group("multiline")
        if inline_ws is not None:
            step_indent = len(ws) + 1 + len(inline_ws)
        else:
            step_indent = len(ws) + len(multiline_ws)
        # Walk back to find the leading ``-`` list marker. In a GitHub Actions
        # workflow the leading ``-`` is at the same indent as the rest of the
        # step's body when ``-`` is on a line of its own (e.g. ``- name:``),
        # OR at the same indent as ``uses:`` when ``-`` shares the line with
        # ``uses:``. We accept either: walk back, ignoring purely sibling
        # attribute lines (those that are deeper than ``-``), until we hit
        # the step's ``-`` marker OR a blank line that separates this step
        # from one above. The first ``-`` line we encounter while scanning
        # backward is the step's start.
        #
        # Inline form (``- uses: alexhawat/mergeCraft@X``) is special: the
        # ``-`` *is* the matched line, so walking back would find the
        # PREVIOUS step's ``-`` and silently include it in our block
        # (which then fails the post-mutation YAML re-parse). Detect the
        # inline form by checking ``m.group("inline")`` -- if set, the
        # matched line is itself the step's start, so we skip the
        # walk-back entirely.
        step_start = cum[i]
        if m.group("inline") is None:
            for j in range(i - 1, -1, -1):
                cur = lines[j]
                if not cur.strip():
                    # Blank line -- boundary.
                    break
                stripped = cur.lstrip(" \t")
                if stripped.startswith("-") and (len(stripped) == 1 or stripped[1] in " :"):
                    step_start = cum[j]
                    break
        # Walk forward to the end. A step terminates at the NEXT sibling
        # step marker -- a ``-`` line at indent <= the current step's
        # ``-`` indent (the step list indent). A ``-`` at deeper indent is
        # block-scalar content (Markdown bullet inside ``prompt: |`` /
        # ``run: |``) and is part of the step's body. This avoids the bug
        # where a Markdown bullet inside a block scalar truncated the step
        # early and the unwire path then silently no-op'd because the
        # owned keys lived past the truncation.
        end = total
        for j in range(i + 1, len(lines)):
            cur = lines[j]
            if not cur.strip():
                continue
            stripped = cur.lstrip(" \t")
            leading = len(cur) - len(stripped)
            # Sibling step marker only if at the step-list indent or
            # shallower. ``step_indent`` is the indent of the matched
            # step's ``uses:`` line, which equals its leading ``-``
            # indent when the step is the ``- uses:`` inline form, or
            # the indent of ``- name:`` when ``-`` lives on its own
            # line (the step's body shares that indent). Either way,
            # a sibling ``-`` must be at <= step_indent.
            if (
                stripped.startswith("-")
                and (len(stripped) == 1 or stripped[1] in " :")
                and leading <= step_indent
            ):
                end = cum[j]
                break
        out.append((step_start, end, step_indent))
    return out


def step_identifier(block: str, fallback_index: int) -> str:
    """Extract a step's ``id:`` or ``name:``; fall back to ``step[{n}]``.

    Note: the parsed-structure counterpart (``_assert_wired_semantics`` /
    ``_assert_unwired_semantics``) falls back to ``job:{job_name}/step:{i}``.
    For nameless matched action steps this means the regex-based identifier
    and the parsed-based identifier will not match -- the caller is
    responsible for translating between the two schemes via
    :func:`_parsed_step_identifiers` before passing them into the post-
    mutation check.
    """
    id_match = re.search(r"^[ \t]*id:[ \t]*(?P<v>\S+)[ \t]*$", block, re.MULTILINE)
    if id_match:
        return str(id_match.group("v"))
    name_match = re.search(r"^[ \t]*name:[ \t]*(?P<v>.+?)[ \t]*$", block, re.MULTILINE)
    if name_match:
        return str(name_match.group("v")).strip()
    return f"step[{fallback_index}]"


def parsed_step_identifiers(
    text: str,
    action_uses: str = ACTION_USES,
) -> list[tuple[int, str]]:
    """Pair each matched ``uses: <action_uses>`` step with its parsed identifier.

    Returns an ordered list of ``(matched_index, parsed_identifier)`` pairs.
    The parsed identifier is the same string the post-mutation check would
    compute for that step: the step's ``id:`` if present, else ``name:``,
    else ``job:{job_name}/step:{i}`` (indexed among all job steps). This
    closes the gap where a nameless action step mutated by
    ``_step_identifier`` returned ``step[N]`` but the parsed-structure
    assertion looked for ``job:{job}/step:{M}``, falsely rejecting a
    successful mutation.
    """
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LogfireWorkflowError(f"could not parse workflow to identify steps: {exc}") from exc
    if not isinstance(parsed, dict):
        return []
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return []
    out: list[tuple[int, str]] = []
    matched_index = 0
    for job_name, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not is_action_uses(uses, action_uses):
                continue
            ident = step.get("id") or step.get("name") or f"job:{job_name}/step:{i}"
            out.append((matched_index, str(ident)))
            matched_index += 1
    return out


def select_step_indices(
    blocks: list[tuple[int, int, int]],
    text: str,
    selector: str,
) -> list[int]:
    """Map a ``--step`` selector (``primary`` / ``all`` / exact id or name) to indices."""
    # The generated merge-group step only reports an existing verdict.
    # Credential and model wiring applies exclusively to review steps.
    review_steps = {
        idx: ident
        for idx, (start, end, _) in enumerate(blocks)
        if (ident := step_identifier(text[start:end], idx)) != "mergecraft_merge_group"
    }
    if not review_steps:
        raise LogfireWorkflowError(f"no ``uses: {ACTION_USES}`` step found in the workflow")
    if selector == "all":
        return list(review_steps)
    if selector == "primary":
        return [next(iter(review_steps))]
    matches = [idx for idx, ident in review_steps.items() if ident == selector]
    if not matches:
        raise LogfireWorkflowError(
            f"--step {selector!r} did not match any ``uses: {ACTION_USES}`` step; "
            f"available: {list(review_steps.values())}"
        )
    return matches


def find_mapping_block(
    text: str,
    key: str,
    *,
    at_indent: int | None = None,
) -> tuple[int, int, int] | None:
    """Return ``(line_start, line_end, key_indent_len)`` for the first ``key:`` block.

    The block consists of the ``key:`` line (plus its trailing newline) and
    every subsequent line whose indent is strictly deeper than the key's
    indent. The block's end is the byte offset of the first line at indent
    <= the key's indent, or end of text. Blank lines inside the block are
    excluded -- they are not children.

    ``line_start`` is the byte offset at the start of the leading whitespace
    of the ``key:`` line; ``line_end`` is the byte offset of the first line
    that does not belong to the block (or end of text).

    ``at_indent`` scopes the search to a specific indent level. When
    provided, a ``key:`` line whose indent is not exactly ``at_indent``
    is skipped. This is how callers prevent literal ``key:`` lines that
    happen to live inside a ``prompt: |`` / ``run: |`` block scalar from
    being mistaken for workflow structure -- the block-scalar content is
    indented deeper than the step's body, and ``at_indent`` is set to the
    step's body indent (the same indent ``uses:`` sits at). Without this
    scoping, ``unwire-workflow`` could pick a script line that happens to
    read ``env: SOMETHING`` as the step's ``env:`` mapping and then the
    parsed-state assertion would silently accept the mismatch.
    """
    lines = text.splitlines(keepends=True)
    cum: list[int] = []
    offset = 0
    for ln in lines:
        cum.append(offset)
        offset += len(ln)
    total = offset

    for i, line in enumerate(lines):
        # ``key:`` line (optionally followed by an inline value: ``key: value``,
        # which we treat as no children, same as GitHub Actions' own parser).
        m = re.match(rf"^(?P<indent>[ \t]*){re.escape(key)}:[ \t]*(?P<rest>\S.*)?$", line)
        if m is None:
            continue
        indent_len = len(m.group("indent"))
        if at_indent is not None and indent_len != at_indent:
            # Literal ``key:`` at the wrong indent -- most often a line of
            # block-scalar content. Skip and keep scanning.
            continue
        block_start = cum[i]
        if m.group("rest"):
            # Inline value -- no children possible.
            return (block_start, cum[i] + len(line), indent_len)
        # Find end of children.
        end = total
        for j in range(i + 1, len(lines)):
            cur = lines[j]
            if not cur.strip():
                continue
            leading = line_indent_len(cur)
            if leading <= indent_len:
                end = cum[j]
                break
        return (block_start, end, indent_len)
    return None


def splice_secret(name: str) -> str:
    """Validate that ``name`` is a plain Actions secret / variable identifier."""
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise LogfireWorkflowError(f"invalid Actions secret / variable name: {name!r}")
    return name


def insert_owned_keys_into_block(
    block: str,
    *,
    key: str,
    canonical: list[tuple[str, str]],
    env_style: bool,
    force: bool,
    at_indent: int | None = None,
) -> tuple[str, bool]:
    """Idempotently insert / replace the canonical owned keys inside one ``key:`` block.

    ``canonical`` is the ordered list of ``(key_name, canonical_value)`` tuples
    the module owns in this mapping; ``env_style`` switches the key-name
    regex from snake-case-friendly ``[A-Za-z0-9_-]+`` to env-var
    ``[A-Z_][A-Z0-9_]*``. ``force=True`` permits overwriting existing values
    that differ from canonical.

    ``at_indent`` scopes the search for ``key:`` to a specific indent --
    the matched ``key:`` line must be at exactly that indent. This prevents
    a literal ``env:`` (or ``tracing-to:``) that lives inside a ``prompt: |``
    block scalar from being mistaken for the step's real mapping, which
    would otherwise corrupt script text and bypass the parsed-state check.

    Strategy: locate the ``key:`` mapping block in ``block``; for every child
    line whose first token (the key) is one of the canonical names, keep it
    if the value matches, replace it if ``force=True``, or record a refusal
    if ``force=False``. For every canonical name not yet seen, append a new
    line at the children indent at the end of the block. The block is
    reconstructed by slicing the original text; siblings before / after the
    block are byte-stable.
    """
    mapping = find_mapping_block(block, key, at_indent=at_indent)
    if mapping is None:
        return block, False
    block_start, block_end, key_indent = mapping

    child_line_re = (
        re.compile(r"^[ \t]*(?P<k>[A-Z_][A-Z0-9_]*):")
        if env_style
        else re.compile(r"^[ \t]*(?P<k>[A-Za-z0-9_-]+):")
    )
    canonical_names = {c[0] for c in canonical}

    # Determine the children indent -- the indent of the first child line --
    # which the mutator uses for any newly-inserted canonical key.
    lines = block[block_start:block_end].splitlines(keepends=True)
    children_indent_str = derive_child_indent(block, block_start, block_end, key_indent)

    if children_indent_str is None and len(lines) == 1:
        # ``key:`` is present but cannot accept children -- either written
        # as ``key: {}`` (flow-style mapping with no entries), as
        # ``key: <inline-value>`` (e.g. ``with: prompt``), or as the bare
        # ``key:`` line followed immediately by a sibling at the same
        # indent. Silently skipping here would leave the step syntactically
        # valid but unwired, and the CLI would print ``wrote`` even though
        # the keys never landed. Refuse loudly instead.
        key_line = lines[0].rstrip("\n")
        raise LogfireWorkflowError(
            f"{key_line!r} has no children; cannot insert owned keys. "
            "Convert it to a block mapping (delete the inline value, "
            f"let ``{key}:`` stand on its own line, then re-run)."
        )

    refused: list[str] = []
    new_lines: list[str] = [lines[0]]  # the ``key:`` line itself.
    seen: set[str] = set()
    child_indent_len = len(children_indent_str) if children_indent_str is not None else None
    for ln in lines[1:]:
        if not ln.strip():
            new_lines.append(ln)
            continue
        leading_spaces = line_indent_len(ln)
        if leading_spaces <= key_indent:
            # Sibling key -- outside this block; preserve.
            new_lines.append(ln)
            continue
        if child_indent_len is not None and leading_spaces != child_indent_len:
            # Deeper than the direct-child indent -- most often the body
            # of a ``prompt: |`` / ``run: |`` block scalar. The strip
            # path already scopes to direct children (so a block-scalar
            # ``tracing-to:`` line isn't silently deleted); the insert
            # path needs the same scoping, otherwise it will treat a
            # literal ``tracing-to: ditto`` line inside ``prompt: |``
            # as a ``with:`` child and refuse the wire (or worse, replace
            # the script text).
            new_lines.append(ln)
            continue
        m = child_line_re.match(ln)
        if m is None or m.group("k") not in canonical_names:
            new_lines.append(ln)
            continue
        key_name = m.group("k")
        target = next(c[1] for c in canonical if c[0] == key_name)
        current_value = ln.split(":", 1)[1].strip()
        if current_value == target:
            new_lines.append(ln)
            seen.add(key_name)
            continue
        if not force:
            refused.append(key_name)
            new_lines.append(ln)
            continue
        # Replace in place, preserving newline.
        new_lines.append(f"{children_indent_str}{key_name}: {target}\n")
        seen.add(key_name)

    if refused:
        raise LogfireWorkflowError(
            "existing values differ from canonical Logfire wiring: "
            f"{sorted(refused)}; pass --force to overwrite"
        )

    modified = False
    if seen:
        # If any of the canonical keys were rewritten or already matched, we
        # *did* inspect the block; only count this as a true modification if
        # any line text actually changed.
        # ``new_lines`` content vs original -- compare by joining.
        orig_inner = "".join(lines[1:])
        new_inner = "".join(new_lines[1:])
        modified = orig_inner != new_inner

    # Append missing canonical keys at the end (before any sibling block).
    if children_indent_str is not None:
        for canonical_key, canonical_value in canonical:
            if canonical_key in seen:
                continue
            # Insert before the first sibling-line if any, otherwise at end.
            insert_idx = len(new_lines)
            for idx in range(1, len(new_lines)):
                ln = new_lines[idx]
                if not ln.strip():
                    continue
                if line_indent_len(ln) <= key_indent:
                    insert_idx = idx
                    break
                insert_idx = idx + 1
            new_lines.insert(
                insert_idx, f"{children_indent_str}{canonical_key}: {canonical_value}\n"
            )
            seen.add(canonical_key)
            modified = True

    new_block_inner = "".join(new_lines)
    if not modified:
        return block, False
    new_block = block[:block_start] + new_block_inner + block[block_end:]
    return new_block, True


def mutate_steps(
    text: str,
    *,
    step_selector: str,
    mutate_one: Callable[[str, int], tuple[str, bool]],
    post_mutation_check: Callable[..., None] | None = None,
) -> WiringChange:
    """Run ``mutate_one(block, step_indent) -> (new_block, modified)`` on each selected step.

    ``step_indent`` is the indent (in characters) of the ``uses:`` line for
    the matched step -- the same indent the step's ``with:`` and ``env:``
    mappings live at. Callers pass it through to ``_find_mapping_block`` so
    a literal ``env:`` line that happens to appear inside a ``prompt: |``
    block scalar (deeper indent) cannot be mistaken for the step's real
    ``env:`` mapping.

    Mutates sequentially from the **last** matching step backward so earlier
    byte offsets remain valid after each in-place splice. After each splice
    the step layout is rescanned.

    ``post_mutation_check`` (optional) is called as
    ``post_mutation_check(cur_text, step_identifiers=...)`` after every splice
    to perform a structural assertion (e.g. owned keys landed in the right
    step's ``with:`` / ``env:`` mappings via ``yaml.safe_load``). It should
    raise :class:`LogfireWorkflowError` on failure. ``step_identifiers`` is
    the ordered list of identifiers (id / name / index fallback) of the
    steps the selector targeted, so callers can restrict assertions to just
    those.
    """
    blocks = find_action_steps(text)
    selected_indices = select_step_indices(blocks, text, step_selector)

    # Resolve each matched action step to its parsed-structure identifier
    # once, before any mutation. This guarantees the same identifier
    # scheme the post-mutation check uses (``job:{job_name}/step:{i}``
    # fallback for nameless steps), so a successful mutation is never
    # rejected by a fallback-string mismatch between the regex and
    # parsed views.
    try:
        parsed_pairs = parsed_step_identifiers(text)
    except LogfireWorkflowError:
        parsed_pairs = []
    parsed_by_matched_index = {mi: ident for mi, ident in parsed_pairs}

    affected: list[str] = []
    cur_text = text
    for idx in sorted(selected_indices, reverse=True):
        start, end, step_indent = blocks[idx]
        block = cur_text[start:end]
        new_block, modified = mutate_one(block, step_indent)
        if not modified:
            continue
        cur_text = cur_text[:start] + new_block + cur_text[end:]
        # Prefer the parsed identifier (single source of truth across the
        # mutator and the post-check); fall back to the regex view only
        # if parsing failed entirely.
        affected.append(parsed_by_matched_index.get(idx) or step_identifier(block, idx))
        blocks = find_action_steps(cur_text)

    ensure_yaml_loadable(cur_text)
    if post_mutation_check is not None:
        # Reverse to preserve selector order (we mutated last-to-first).
        selected_identifiers = list(reversed(affected))
        post_mutation_check(cur_text, step_identifiers=selected_identifiers)
    return WiringChange(old_text=text, new_text=cur_text, affected_steps=list(reversed(affected)))


def ensure_yaml_loadable(text: str) -> None:
    """Re-parse ``text`` via PyYAML; raise on syntax errors that the surgery could have introduced."""
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LogfireWorkflowError(f"mutation produced invalid YAML: {exc}") from exc


def create_with_block(
    block: str,
    canonical: list[tuple[str, str]],
    at_indent: int | None = None,
) -> str:
    """Insert a fresh ``with:`` block immediately after the ``uses:`` line.

    Symmetric with ``_create_env_block`` but on the opposite side: when a
    step has no ``with:`` mapping (every ``action.yml`` input is optional,
    and the README's Example 1 defines only ``env:`` on the step), we have
    to synthesise a ``with:`` block to host the three owned input keys
    (``tracing``, ``tracing-to``, ``logfire-token``). Placement is after the
    step's ``uses:`` line so the new block sits at the canonical sibling
    position. Child indent falls back to ``at_indent + 2`` when ``env:``
    is missing too (the common env-only case has ``env:`` so we mirror its
    child indent); this keeps wire -> unwire symmetric on such files: the
    wire writes at the observed indent, the unwire scans at the same
    indent.

    ``at_indent`` scopes the search for the existing ``env:`` mapping
    line to the step's body indent -- prevents a literal ``env:`` line
    inside a block scalar from being mistaken for the step's real ``env:``
    mapping.
    """
    # Match both step shapes documented by the README -- multi-line
    # ``- name: foo`` / ``  uses: ...`` and inline ``- uses: ...``. The
    # ``(?P<uses_line>[^\n]*\n)`` capture preserves the whole ``uses:``
    # line so we can insert immediately after it. The new ``with:`` key
    # sits at the column of ``uses:`` itself (the body indent), which
    # equals ``at_indent`` -- passed in by the caller rather than
    # reconstructed from the regex (otherwise inline-vs-multiline
    # disambiguation has to be repeated here).
    uses_re = re.compile(
        r"^(?P<ws>[ \t]*)(?:-(?P<inline>[ \t]+)|(?P<multiline>[ \t]+))"
        r"uses:[ \t]*(?P<uses_line>[^\n]*\n)",
        re.MULTILINE,
    )
    m = uses_re.search(block)
    if m is None:
        raise LogfireWorkflowError(
            "could not locate the ``uses:`` line to attach a new ``with:`` block"
        )
    indent_str = " " * at_indent if at_indent is not None else ""
    # Try to mirror the existing ``env:`` block's child indent so the new
    # ``with:`` block matches the workflow's own style (e.g. 4-space
    # indentation on workflows that opt into it). Fall back to
    # ``at_indent + 2`` when ``env:`` is missing or has no children yet.
    env_block = find_mapping_block(block, "env", at_indent=at_indent)
    if env_block is not None:
        child_ws = derive_child_indent(block, env_block[0], env_block[1], env_block[2])
        child_indent = child_ws if child_ws is not None else indent_str + "  "
    else:
        child_indent = indent_str + "  "
    insertion_lines = [f"{indent_str}with:"]
    for key, value in canonical:
        insertion_lines.append(f"{child_indent}{key}: {value}")
    insertion = "\n".join(insertion_lines) + "\n"
    return block[: m.end()] + insertion + block[m.end() :]


def create_env_block(
    block: str, canonical: list[tuple[str, str]], at_indent: int | None = None
) -> str:
    """Insert a fresh ``env:`` block immediately after the ``with:`` block.

    When the step has no ``with:`` block the new ``env:`` is appended after
    the ``uses:`` line (the canonical sibling placement). The new block holds
    one child line per entry in *canonical*, in order, at the canonical
    child indent -- which we derive from the existing ``with:`` block's
    observed child indent when present (falling back to ``+2``), so the
    new ``env:`` mirrors the workflow's own style even on non-canonical
    indentation (e.g. 4-space). This keeps wire -> unwire symmetric on such
    files: the wire writes at the dynamic indent, the unwire scans at the
    same dynamic indent.

    ``at_indent`` scopes the search for the existing ``with:`` mapping
    line to the step's body indent -- prevents a literal ``with:`` line
    inside a block scalar from being mistaken for the step's real ``with:``
    mapping.
    """
    if not canonical:
        msg = "_create_env_block requires at least one canonical entry"
        raise LogfireWorkflowError(msg)

    def _children(child_indent: str) -> str:
        # Every owned key the caller asked for, not just the first. Rendering
        # a subset here silently drops keys (e.g. MERGECRAFT_TRACING_REGION)
        # on the env-less step shape, and the wired-semantics check would not
        # catch it because only REQUIRED_ENV_KEYS is asserted.
        return "".join(f"{child_indent}{key}: {value}\n" for key, value in canonical)

    # Prefer inserting after the ``with:`` block (its trailing `block_end`).
    with_block = find_mapping_block(block, "with", at_indent=at_indent)
    if with_block is not None:
        with_end = with_block[1]
        # The indent for the new ``env:`` key is the same as ``with:``'s indent.
        with_indent = " " * with_block[2]
        # Derive the child indent from the existing ``with:`` children so
        # the new ``env:`` block matches the workflow's own style. Fall
        # back to ``+2`` only if ``with:`` has no children (which the
        # ``LogfireWorkflowError`` above already forbids for the wire
        # path, but be defensive for callers that go straight here).
        child_ws = derive_child_indent(block, with_block[0], with_block[1], with_block[2])
        env_child_indent = child_ws if child_ws is not None else with_indent + "  "
        insertion = f"{with_indent}env:\n" + _children(env_child_indent)
        return block[:with_end] + insertion + block[with_end:]
    # No ``with:`` -- fall back to inserting after ``uses:``. Match both
    # step shapes documented by the README -- multi-line
    # ``- name: foo`` / ``  uses: ...`` and inline ``- uses: ...``.
    uses_re = re.compile(
        r"^(?P<indent>[ \t]*)(?:-(?P<inline>[ \t]+)|(?P<multiline>[ \t]+))"
        r"uses:[ \t]*(?P<uses_line>[^\n]*\n)",
        re.MULTILINE,
    )
    m = uses_re.search(block)
    if m is None:
        raise LogfireWorkflowError(
            "could not locate the ``uses:`` line to attach a new ``env:`` block"
        )
    indent_str = " " * at_indent if at_indent is not None else ""
    env_indent = indent_str + "  "
    insertion = f"{indent_str}env:\n" + _children(env_indent)
    return block[: m.end()] + insertion + block[m.end() :]


def render_workflow_diff(workflow_path: Path, change: WiringChange, *, max_lines: int = 200) -> str:
    """Return a unified-diff text between ``change.old_text`` and ``change.new_text``."""
    rel = str(workflow_path)
    diff = difflib.unified_diff(
        change.old_text.splitlines(keepends=True),
        change.new_text.splitlines(keepends=True),
        fromfile=f"{rel} (current)",
        tofile=f"{rel} (proposed)",
        lineterm="",
    )
    lines = list(diff)
    if len(lines) > max_lines:
        truncation = f"... ({len(lines) - max_lines} more lines truncated)\n"
        lines = [*lines[:max_lines], truncation]
    return "".join(line if line.endswith("\n") else f"{line}\n" for line in lines)


WorkflowYamlError = LogfireWorkflowError
WorkflowChange = WiringChange


__all__ = [
    "ACTION_USES",
    "DEFAULT_WORKFLOW_RELATIVE_PATH",
    "LogfireWorkflowError",
    "WiringChange",
    "WorkflowChange",
    "WorkflowYamlError",
    "create_env_block",
    "create_with_block",
    "derive_child_indent",
    "ensure_yaml_loadable",
    "find_action_steps",
    "find_mapping_block",
    "insert_owned_keys_into_block",
    "is_action_uses",
    "line_indent_len",
    "mutate_steps",
    "parsed_step_identifiers",
    "render_workflow_diff",
    "select_step_indices",
    "splice_secret",
    "step_identifier",
]
