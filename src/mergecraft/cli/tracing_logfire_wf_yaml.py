"""Surgical YAML mutator for ``mergecraft tracing logfire wire-workflow``.

Why not PyYAML round-trip:
    The consumer workflow file (``.github/workflows/mergecraft.yml`` in the
    mergeCraft self-review workflow, and the mirror in sevn-bot/sevn) carries
    dozens of hand-written ``#`` comments documenting cascade shape, provider
    priority, and rationale for each step. PyYAML round-trip load / dump
    strips every comment and re-flows string quoting to its own convention,
    which would silently turn a clean PR review into a 2\u202f000-line whitespace
    diff. ``ruamel.yaml`` would fix it but adds a runtime dep for a 200-line
    helper.

    So the strategy is: PyYAML **parses** for assertions only (does the file
    have a ``jobs:`` block, does an ``alexhawat/mergeCraft`` step exist,
    what's its ``id:``); a small line-based mutation **edits** the four
    owned keys inside the targeted step's ``with:`` and ``env:`` blocks;
    PyYAML **re-parses** the result to confirm the mutation didn't introduce
    syntax errors. Comments and unrelated YAML are byte-stable.

Exports:
    DEFAULT_WORKFLOW_RELATIVE_PATH -- default ``--workflow`` value.
    LogfireWorkflowError -- raised on hard failures (no step matches,
        malformed YAML after mutation, mismatched existing values that
        ``--force`` did not waive).
    WiringChange -- result of ``apply_logfire_wiring`` /
        ``remove_logfire_wiring`` carrying the modified text and the
        affected step identifiers.
    apply_logfire_wiring -- idempotent insert of the four owned keys.
    remove_logfire_wiring -- idempotent removal of the four owned keys.
    render_workflow_diff -- unified diff between old and proposed text.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_WORKFLOW_RELATIVE_PATH = ".github/workflows/mergecraft.yml"

# The exact ``uses:`` value this module wires into. GitHub treats
# ``alexhawat/mergeCraft`` (canonical, capital C) and ``alexhawat/mergecraft``
# (lowercased in chat) as different owners at the URL level, but the
# operator-facing reference is the canonical form. Matching exactly avoids
# silently mutating forks with a similarly-named action.
_ACTION_USES = "alexhawat/mergeCraft"

# Owned keys -- every key whose value this module is willing to insert
# or strip. Kept as tuples so callers (and tests) can import them.
OWNED_WITH_KEYS: tuple[str, ...] = ("tracing", "tracing-to", "logfire-token")
OWNED_ENV_KEYS: tuple[str, ...] = ("MERGECRAFT_TRACING_PROJECT",)

# Indent units. The upstream convention is two-space indent for keys under a
# step (``uses:`` at 8 spaces, ``with:``/``env:`` at 8 spaces, children at
# 10 or 12). The mutator re-derives the children's indent dynamically from
# the observed ``with:`` / ``env:`` key line; no fixed default is needed.


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


# ---------------------------------------------------------------------------
# Step detection
# ---------------------------------------------------------------------------


def _line_indent_len(line: str) -> int:
    """Return the indent (in characters) of ``line``. Blank lines return 0."""
    if not line.strip():
        return 0
    return len(line) - len(line.lstrip(" \t"))


def _find_action_steps(text: str, action_uses: str = _ACTION_USES) -> list[tuple[int, int, int]]:
    """Locate every ``uses: <action_uses>`` step in ``text``.

    Returns a list of ``(step_start, step_end, step_indent_len)`` tuples.
    ``step_start`` is the byte offset of the line containing the leading ``-``
    list marker; ``step_end`` is the byte offset of the first line at the
    same or shallower indent, or end of file. ``step_indent_len`` is the
    number of leading whitespace characters on the leading ``-`` line.
    """
    lines = text.splitlines(keepends=True)
    out: list[tuple[int, int, int]] = []
    uses_re = re.compile(r"^(?P<indent>[ \t]+)uses:[ \t]*" + re.escape(action_uses) + r"\b")
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
        step_indent = len(m.group("indent"))
        # Walk back to find the leading ``-`` list marker. In a GitHub Actions
        # workflow the leading ``-`` is at the same indent as the rest of the
        # step's body when ``-`` is on a line of its own (e.g. ``- name:``),
        # OR at the same indent as ``uses:`` when ``-`` shares the line with
        # ``uses:``. We accept either: walk back, ignoring purely sibling
        # attribute lines (those that are deeper than ``-``), until we hit
        # the step's ``-`` marker OR a blank line that separates this step
        # from one above. The first ``-`` line we encounter while scanning
        # backward is the step's start.
        step_start = cum[i]
        for j in range(i - 1, -1, -1):
            cur = lines[j]
            if not cur.strip():
                # Blank line -- boundary.
                break
            stripped = cur.lstrip(" \t")
            if stripped.startswith("-") and (len(stripped) == 1 or stripped[1] in " :"):
                step_start = cum[j]
                break
        # Walk forward to the end -- the next ``-`` list marker at any indent
        # terminates the step.
        end = total
        for j in range(i + 1, len(lines)):
            cur = lines[j]
            if not cur.strip():
                continue
            stripped = cur.lstrip(" \t")
            if stripped.startswith("-") and (len(stripped) == 1 or stripped[1] in " :"):
                end = cum[j]
                break
        out.append((step_start, end, step_indent))
    return out


def _step_identifier(block: str, fallback_index: int) -> str:
    """Extract a step's ``id:`` or ``name:``; fall back to ``step[{n}]``."""
    id_match = re.search(r"^[ \t]*id:[ \t]*(?P<v>\S+)[ \t]*$", block, re.MULTILINE)
    if id_match:
        return str(id_match.group("v"))
    name_match = re.search(r"^[ \t]*name:[ \t]*(?P<v>.+?)[ \t]*$", block, re.MULTILINE)
    if name_match:
        return str(name_match.group("v")).strip()
    return f"step[{fallback_index}]"


def _select_step_indices(
    blocks: list[tuple[int, int, int]],
    text: str,
    selector: str,
) -> list[int]:
    """Map a ``--step`` selector (``primary`` / ``all`` / exact id or name) to indices."""
    if not blocks:
        raise LogfireWorkflowError(f"no ``uses: {_ACTION_USES}`` step found in the workflow")
    if selector == "all":
        return list(range(len(blocks)))
    if selector == "primary":
        return [0]
    matches: list[int] = []
    for idx, (start, end, _indent) in enumerate(blocks):
        block = text[start:end]
        ident = _step_identifier(block, idx)
        if ident == selector:
            matches.append(idx)
    if not matches:
        avail = [_step_identifier(text[s:e], i) for i, (s, e, _) in enumerate(blocks)]
        raise LogfireWorkflowError(
            f"--step {selector!r} did not match any ``uses: {_ACTION_USES}`` step; "
            f"available: {avail}"
        )
    return matches


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------


def _find_mapping_block(text: str, key: str) -> tuple[int, int, int] | None:
    """Return ``(line_start, line_end, key_indent_len)`` for the first ``key:`` block.

    The block consists of the ``key:`` line (plus its trailing newline) and
    every subsequent line whose indent is strictly deeper than the key's
    indent. The block's end is the byte offset of the first line at indent
    <= the key's indent, or end of text. Blank lines inside the block are
    excluded -- they are not children.

    ``line_start`` is the byte offset at the start of the leading whitespace
    of the ``key:`` line; ``line_end`` is the byte offset of the first line
    that does not belong to the block (or end of text).
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
            leading = _line_indent_len(cur)
            if leading <= indent_len:
                end = cum[j]
                break
        return (block_start, end, indent_len)
    return None


# ---------------------------------------------------------------------------
# Insert / strip helpers
# ---------------------------------------------------------------------------


def _splice_secret(name: str) -> str:
    """Validate that ``name`` is a plain Actions secret / variable identifier."""
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise LogfireWorkflowError(f"invalid Actions secret / variable name: {name!r}")
    return name


def _insert_owned_keys_into_block(
    block: str,
    *,
    key: str,
    canonical: list[tuple[str, str]],
    env_style: bool,
    force: bool,
) -> tuple[str, bool]:
    """Idempotently insert / replace the canonical owned keys inside one ``key:`` block.

    ``canonical`` is the ordered list of ``(key_name, canonical_value)`` tuples
    the module owns in this mapping; ``env_style`` switches the key-name
    regex from snake-case-friendly ``[A-Za-z0-9_-]+`` to env-var
    ``[A-Z_][A-Z0-9_]*``. ``force=True`` permits overwriting existing values
    that differ from canonical.

    Strategy: locate the ``key:`` mapping block in ``block``; for every child
    line whose first token (the key) is one of the canonical names, keep it
    if the value matches, replace it if ``force=True``, or record a refusal
    if ``force=False``. For every canonical name not yet seen, append a new
    line at the children indent at the end of the block. The block is
    reconstructed by slicing the original text; siblings before / after the
    block are byte-stable.
    """
    mapping = _find_mapping_block(block, key)
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
    children_indent_str: str | None = None
    for ln in lines[1:]:
        if not ln.strip():
            continue
        leading_spaces = _line_indent_len(ln)
        if leading_spaces <= key_indent:
            break
        children_indent_str = ln[:leading_spaces]
        break

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
    for ln in lines[1:]:
        if not ln.strip():
            new_lines.append(ln)
            continue
        leading_spaces = _line_indent_len(ln)
        if leading_spaces <= key_indent:
            # Sibling key -- outside this block; preserve.
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
                if _line_indent_len(ln) <= key_indent:
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


def _strip_owned_keys(block: str) -> tuple[str, bool]:
    """Remove ``OWNED_WITH_KEYS`` lines from ``with:`` and ``OWNED_ENV_KEYS`` from ``env:``.

    Scoped to the *direct children* of the step's ``with:`` / ``env:``
    mappings at the canonical child indent. Lines inside a ``run: |`` /
    ``prompt: |`` / ``script: |`` block-scalar are at a deeper indent and
    are not touched -- a previous, unscoped implementation matched owned-key-
    shaped lines at any indent and could silently delete script text that
    happened to contain a literal ``tracing:`` line. The parsed-state
    assertion can't see that data loss (block-scalar content is opaque to
    the loader), so the scoping has to happen here.
    """
    owned = set(OWNED_WITH_KEYS) | set(OWNED_ENV_KEYS)
    owned_re = re.compile(r"^[ \t]*(?P<k>[A-Za-z0-9_-]+|MERGECRAFT_[A-Z_]+):.*\n")
    modified = False

    # Slice the block into "owned mapping blocks" (``with:`` / ``env:``) and
    # "everything else" (sibling attributes, block scalars, blank lines).
    # Strip only the direct children of the owned mapping blocks.
    with_block = _find_mapping_block(block, "with")
    env_block = _find_mapping_block(block, "env")
    owned_ranges: list[tuple[int, int, int]] = []
    if with_block is not None:
        # Child indent is two spaces deeper than the ``with:`` key indent.
        owned_ranges.append((with_block[0], with_block[1], with_block[2] + 2))
    if env_block is not None:
        owned_ranges.append((env_block[0], env_block[1], env_block[2] + 2))

    if not owned_ranges:
        # No ``with:`` / ``env:`` mapping in this step -- nothing to strip.
        return block, False

    # For each owned mapping, scan its child lines at the canonical indent
    # and drop those whose key matches an owned name. Rebuild the block
    # by stitching together unmodified sibling regions and the cleaned
    # child region.
    pieces: list[str] = []
    last = 0
    for block_start, block_end, child_indent in owned_ranges:
        # Emit everything between ``last`` and the start of this mapping
        # block untouched (sibling attributes, the ``with:``/``env:`` key
        # line itself, etc.).
        pieces.append(block[last:block_start])
        # The block starts at the start of the ``key:`` line -- we need
        # to re-emit that line first, then process its children.
        lines = block[block_start:block_end].splitlines(keepends=True)
        if not lines:
            pieces.append(block[block_start:block_end])
            last = block_end
            continue
        pieces.append(lines[0])  # the ``with:`` / ``env:`` line.
        for ln in lines[1:]:
            stripped = ln.strip()
            if not stripped:
                pieces.append(ln)
                continue
            leading = _line_indent_len(ln)
            if leading <= (child_indent - 2):
                # Sibling of ``with:``/``env:`` -- outside this mapping.
                pieces.append(ln)
                continue
            if leading != child_indent:
                # Deeper than the direct-child indent -- likely inside a
                # block scalar (``prompt: |`` / ``run: |``). Preserve
                # verbatim so we never touch script text.
                pieces.append(ln)
                continue
            m = owned_re.match(ln)
            if m is not None and m.group("k") in owned:
                modified = True
                continue  # drop the line.
            pieces.append(ln)
        last = block_end
    pieces.append(block[last:])
    return "".join(pieces), modified


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _mutate_steps(
    text: str,
    *,
    step_selector: str,
    mutate_one: Callable[[str], tuple[str, bool]],
    post_mutation_check: Callable[..., None] | None = None,
) -> WiringChange:
    """Run ``mutate_one(block) -> (new_block, modified)`` on each selected step.

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
    blocks = _find_action_steps(text)
    selected_indices = _select_step_indices(blocks, text, step_selector)

    affected: list[str] = []
    cur_text = text
    for idx in sorted(selected_indices, reverse=True):
        start, end, _indent = blocks[idx]
        block = cur_text[start:end]
        new_block, modified = mutate_one(block)
        if not modified:
            continue
        cur_text = cur_text[:start] + new_block + cur_text[end:]
        affected.append(_step_identifier(block, idx))
        blocks = _find_action_steps(cur_text)

    _ensure_yaml_loadable(cur_text)
    if post_mutation_check is not None:
        # Reverse to preserve selector order (we mutated last-to-first).
        selected_identifiers = list(reversed(affected))
        post_mutation_check(cur_text, step_identifiers=selected_identifiers)
    return WiringChange(old_text=text, new_text=cur_text, affected_steps=list(reversed(affected)))


def _ensure_yaml_loadable(text: str) -> None:
    """Re-parse ``text`` via PyYAML; raise on syntax errors that the surgery could have introduced."""
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LogfireWorkflowError(f"mutation produced invalid YAML: {exc}") from exc


def _assert_wired_semantics(text: str, *, step_identifiers: list[str]) -> None:
    """Confirm every selected ``uses: alexhawat/mergeCraft`` step carries the owned keys.

    Uses :func:`yaml.safe_load` (which we already trust to confirm parseability)
    to assert each *selected* ``alexhawat/mergeCraft`` step has ``tracing`` /
    ``tracing-to`` / ``logfire-token`` keys in its ``with:`` mapping and
    ``MERGECRAFT_TRACING_PROJECT`` in its ``env:`` mapping. This catches
    silent partial wirings -- a step whose ``with:`` was inline
    (``with: {}`` or ``with: prompt``) and therefore had no children to
    insert into, leaving the file syntactically valid but unwired. Also
    catches a ``run: |`` block-scalar whose content fooled the line-based
    detector into splicing keys into a script line.

    ``step_identifiers`` is the ordered list of identifiers (id / name / index
    fallback) of the steps the selector targeted; only those steps are
    checked. Other ``alexhawat/mergeCraft`` steps the operator didn't target
    (e.g. a sibling fallback step under ``--step mergecraft_primary``) are
    not asserted.
    """
    if not step_identifiers:
        return  # nothing to assert; a selector that matched zero steps is a separate error.
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # ``_ensure_yaml_loadable`` runs first and would already have raised
        # on a syntax error; this is a belt-and-braces second guard.
        raise LogfireWorkflowError(f"mutation produced invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        return
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return
    targets = set(step_identifiers)
    unwired: list[str] = []
    seen_targets: set[str] = set()
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
            if not isinstance(uses, str) or not uses.startswith(_ACTION_USES):
                continue
            step_id = step.get("id") or step.get("name") or f"job:{job_name}/step:{i}"
            if step_id not in targets:
                continue
            seen_targets.add(step_id)
            with_map = step.get("with")
            if not isinstance(with_map, dict):
                unwired.append(
                    f"{step_id}: with: is {with_map!r} (not a mapping); "
                    "cannot carry the four owned keys"
                )
                continue
            for key in OWNED_WITH_KEYS:
                if key not in with_map:
                    unwired.append(f"{step_id}: missing with.{key}")
            env_map = step.get("env")
            if env_map is not None and not isinstance(env_map, dict):
                unwired.append(
                    f"{step_id}: env: is {env_map!r} (not a mapping); "
                    "cannot carry MERGECRAFT_TRACING_PROJECT"
                )
                continue
            if isinstance(env_map, dict):
                for key in OWNED_ENV_KEYS:
                    if key not in env_map:
                        unwired.append(f"{step_id}: missing env.{key}")
    missing = targets - seen_targets
    if missing:
        unwired.append(f"selected step(s) not present in parsed workflow: {sorted(missing)}")
    if unwired:
        joined = "; ".join(unwired)
        raise LogfireWorkflowError(f"mergeCraft step(s) not fully wired after mutation: {joined}")


def _assert_unwired_semantics(text: str, *, step_identifiers: list[str]) -> None:
    """Confirm every selected step has no surviving owned keys (for remove)."""
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return  # ``_ensure_yaml_loadable`` already raised; nothing to add.
    if not isinstance(parsed, dict):
        return
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return
    targets = set(step_identifiers)
    stale: list[str] = []
    owned = set(OWNED_WITH_KEYS) | set(OWNED_ENV_KEYS)
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
            if not isinstance(uses, str) or not uses.startswith(_ACTION_USES):
                continue
            step_id = step.get("id") or step.get("name") or f"job:{job_name}/step:{i}"
            if step_id not in targets:
                continue
            with_map = step.get("with")
            if isinstance(with_map, dict):
                for key in owned & set(with_map):
                    stale.append(f"{step_id}: with.{key} still present")
            env_map = step.get("env")
            if isinstance(env_map, dict):
                for key in owned & set(env_map):
                    stale.append(f"{step_id}: env.{key} still present")
    if stale:
        joined = "; ".join(stale)
        raise LogfireWorkflowError(
            f"mergeCraft step(s) still carry owned keys after unwire: {joined}"
        )


def apply_logfire_wiring(
    *,
    workflow_path: Path,
    secret_name: str,
    project_var_name: str,
    step_selector: str,
    force: bool,
) -> WiringChange:
    """Insert the four owned keys into every selected ``uses:`` step in ``workflow_path``."""
    try:
        text = workflow_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LogfireWorkflowError(f"workflow file not found: {workflow_path}") from exc
    except OSError as exc:
        raise LogfireWorkflowError(f"could not read {workflow_path}: {exc}") from exc
    _splice_secret(secret_name)
    _splice_secret(project_var_name)

    with_canonical: list[tuple[str, str]] = [
        ("tracing", '"true"'),
        ("tracing-to", "logfire"),
        ("logfire-token", f"${{{{ secrets.{_splice_secret(secret_name)} }}}}"),
    ]
    env_canonical: list[tuple[str, str]] = [
        ("MERGECRAFT_TRACING_PROJECT", f"${{{{ vars.{_splice_secret(project_var_name)} }}}}"),
    ]

    def _do(block: str) -> tuple[str, bool]:
        # Order matters: insert ``with:`` keys first so an existing ``env:``
        # block's byte offsets used by the second call haven't been perturbed.
        block2, mod_with = _insert_owned_keys_into_block(
            block, key="with", canonical=with_canonical, env_style=False, force=force
        )
        # The step *must* have a ``with:`` block at this point: the mergeCraft
        # action requires it, and the prior mutation was a no-op only if it
        # already existed. There is no concept of a step with no ``with:``.
        block3, mod_env = _insert_owned_keys_into_block(
            block2, key="env", canonical=env_canonical, env_style=True, force=force
        )
        if not mod_env and _find_mapping_block(block2, "env") is None:
            # ``env:`` block is genuinely absent -- create one immediately
            # after the ``with:`` block (or after ``uses:`` if no ``with:``).
            block3 = _create_env_block(block2, env_canonical[0])
            mod_env = True
        return block3, mod_with or mod_env

    return _mutate_steps(
        text,
        step_selector=step_selector,
        mutate_one=_do,
        post_mutation_check=_assert_wired_semantics,
    )


def _create_env_block(block: str, canonical: tuple[str, str]) -> str:
    """Insert a fresh ``env:`` block immediately after the ``with:`` block.

    When the step has no ``with:`` block the new ``env:`` is appended after
    the ``uses:`` line (the canonical sibling placement). The new block holds
    a single child line ``MERGECRAFT_TRACING_PROJECT`` at the canonical
    child indent -- two spaces deeper than the ``env:`` key, which is
    itself at the same indent as the ``with:`` key (or ``uses:`` line).
    """
    canonical_key, canonical_value = canonical
    # Prefer inserting after the ``with:`` block (its trailing `block_end`).
    with_block = _find_mapping_block(block, "with")
    if with_block is not None:
        with_end = with_block[1]
        # The indent for the new ``env:`` key is the same as ``with:``'s indent.
        with_indent = " " * with_block[2]
        env_indent = with_indent + "  "
        insertion = f"{with_indent}env:\n{env_indent}{canonical_key}: {canonical_value}\n"
        return block[:with_end] + insertion + block[with_end:]
    # No ``with:`` -- fall back to inserting after ``uses:``.
    uses_re = re.compile(r"^(?P<indent>[ \t]*)uses:[ \t]*\S+[^\n]*\n", re.MULTILINE)
    m = uses_re.search(block)
    if m is None:
        raise LogfireWorkflowError(
            "could not locate the ``uses:`` line to attach a new ``env:`` block"
        )
    indent_str = m.group("indent")
    env_indent = indent_str + "  "
    insertion = f"{indent_str}env:\n{env_indent}{canonical_key}: {canonical_value}\n"
    return block[: m.end()] + insertion + block[m.end() :]


def remove_logfire_wiring(
    *,
    workflow_path: Path,
    step_selector: str,
) -> WiringChange:
    """Strip every owned key from every selected step in ``workflow_path``."""
    try:
        text = workflow_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LogfireWorkflowError(f"workflow file not found: {workflow_path}") from exc
    return _mutate_steps(
        text,
        step_selector=step_selector,
        mutate_one=_strip_owned_keys,
        post_mutation_check=_assert_unwired_semantics,
    )


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


__all__ = [
    "DEFAULT_WORKFLOW_RELATIVE_PATH",
    "OWNED_ENV_KEYS",
    "OWNED_WITH_KEYS",
    "LogfireWorkflowError",
    "WiringChange",
    "apply_logfire_wiring",
    "remove_logfire_wiring",
    "render_workflow_diff",
]
