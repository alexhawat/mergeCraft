"""Surgical YAML mutator for ``mergecraft tracing logfire wire-workflow``.

Uses :mod:`mergecraft.workflow.yaml_edit` for comment-preserving edits.

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

import re
from pathlib import Path

import yaml

from mergecraft.workflow.yaml_edit import (
    ACTION_USES,
    create_env_block,
    create_with_block,
    derive_child_indent,
    ensure_yaml_loadable,
    find_action_steps,
    find_mapping_block,
    insert_owned_keys_into_block,
    is_action_uses,
    line_indent_len,
    mutate_steps,
    parsed_step_identifiers,
    select_step_indices,
    splice_secret,
    step_identifier,
)
from mergecraft.workflow.yaml_edit import (
    DEFAULT_WORKFLOW_RELATIVE_PATH as DEFAULT_WORKFLOW_RELATIVE_PATH,
)
from mergecraft.workflow.yaml_edit import (
    LogfireWorkflowError as LogfireWorkflowError,
)
from mergecraft.workflow.yaml_edit import (
    WiringChange as WiringChange,
)
from mergecraft.workflow.yaml_edit import (
    render_workflow_diff as render_workflow_diff,
)

# Compatibility for existing imports of the shared helper names.
_ACTION_USES = ACTION_USES
_is_action_uses = is_action_uses
_line_indent_len = line_indent_len
_derive_child_indent = derive_child_indent
_find_action_steps = find_action_steps
_step_identifier = step_identifier
_parsed_step_identifiers = parsed_step_identifiers
_select_step_indices = select_step_indices
_find_mapping_block = find_mapping_block
_splice_secret = splice_secret
_insert_owned_keys_into_block = insert_owned_keys_into_block
_mutate_steps = mutate_steps
_ensure_yaml_loadable = ensure_yaml_loadable
_create_with_block = create_with_block
_create_env_block = create_env_block

# Owned keys -- every key whose value this module is willing to insert
# or strip. Kept as tuples so callers (and tests) can import them.
OWNED_WITH_KEYS: tuple[str, ...] = ("tracing", "tracing-to", "logfire-token")
OWNED_ENV_KEYS: tuple[str, ...] = (
    "MERGECRAFT_TRACING_PROJECT",
    "MERGECRAFT_TRACING_REGION",
)

# The subset of ``OWNED_ENV_KEYS`` that must be present after a wire for the
# result to count as fully wired. ``MERGECRAFT_TRACING_REGION`` is opt-in
# (``wire-workflow --region``) because the resolver already defaults to ``us``
# when it is absent, so a wire that omits it is complete, not partial. It still
# belongs to ``OWNED_ENV_KEYS`` so ``unwire-workflow`` strips it.
REQUIRED_ENV_KEYS: tuple[str, ...] = ("MERGECRAFT_TRACING_PROJECT",)


def _strip_owned_keys(block: str, at_indent: int | None = None) -> tuple[str, bool]:
    """Remove ``OWNED_WITH_KEYS`` lines from ``with:`` and ``OWNED_ENV_KEYS`` from ``env:``.

    Scoped to the *direct children* of the step's ``with:`` / ``env:``
    mappings at the canonical child indent. Lines inside a ``run: |`` /
    ``prompt: |`` / ``script: |`` block-scalar are at a deeper indent and
    are not touched -- a previous, unscoped implementation matched owned-key-
    shaped lines at any indent and could silently delete script text that
    happened to contain a literal ``tracing:`` line. The parsed-state
    assertion can't see that data loss (block-scalar content is opaque to
    the loader), so the scoping has to happen here.

    ``at_indent`` scopes the search for the ``with:`` / ``env:`` mapping
    lines themselves to a specific indent -- prevents a literal ``env:``
    line inside a ``prompt: |`` block scalar from being mistaken for the
    step's real ``env:`` mapping (which would corrupt script text and
    bypass the parsed-state check).
    """
    owned = set(OWNED_WITH_KEYS) | set(OWNED_ENV_KEYS)
    owned_re = re.compile(r"^[ \t]*(?P<k>[A-Za-z0-9_-]+|MERGECRAFT_[A-Z_]+):.*\n")
    modified = False

    # Slice the block into "owned mapping blocks" (``with:`` / ``env:``) and
    # "everything else" (sibling attributes, block scalars, blank lines).
    # Strip only the direct children of the owned mapping blocks.
    with_block = _find_mapping_block(block, "with", at_indent=at_indent)
    env_block = _find_mapping_block(block, "env", at_indent=at_indent)
    owned_ranges: list[tuple[int, int, int, str]] = []
    if with_block is not None:
        # Derive the canonical child indent from the observed ``with:``
        # children -- the *same* derivation the insert path uses. A previous
        # version hardcoded ``key_indent + 2`` here, which made wire -> unwire
        # round trips silently no-op on workflows that use a non-canonical
        # child indent (e.g. 4-space style): the wire would insert at the
        # dynamic +6 indent, the unwire would only scan at the hardcoded +2,
        # and the keys would remain while the CLI printed "had no Logfire
        # wiring; no changes needed" and exited 0.
        child_indent_ws = _derive_child_indent(block, with_block[0], with_block[1], with_block[2])
        if child_indent_ws is None:
            # ``with:`` exists but has no children -- same inline-mapping
            # refusal as the insert path. Better to fail loudly here than
            # to silently no-op and let the post-check pass on an empty
            # target set.
            with_key_line = block[with_block[0] : with_block[1]].splitlines(keepends=False)[0]
            raise LogfireWorkflowError(
                f"{with_key_line!r} has no children; cannot strip owned keys. "
                "Convert it to a block mapping (delete the inline value, "
                "let ``with:`` stand on its own line, then re-run)."
            )
        owned_ranges.append((with_block[0], with_block[1], len(child_indent_ws), "with"))
    if env_block is not None:
        child_indent_ws = _derive_child_indent(block, env_block[0], env_block[1], env_block[2])
        if child_indent_ws is None:
            env_key_line = block[env_block[0] : env_block[1]].splitlines(keepends=False)[0]
            raise LogfireWorkflowError(
                f"{env_key_line!r} has no children; cannot strip owned keys. "
                "Convert it to a block mapping (delete the inline value, "
                "let ``env:`` stand on its own line, then re-run)."
            )
        owned_ranges.append((env_block[0], env_block[1], len(child_indent_ws), "env"))

    if not owned_ranges:
        # No ``with:`` / ``env:`` mapping in this step -- nothing to strip.
        return block, False

    # Stitch the cleaned mappings back in *byte order*. ``with:`` and
    # ``env:`` can appear in either order in valid YAML; an unsorted loop
    # would advance ``last`` through the later mapping first and then
    # re-emit the earlier mapping, duplicating / reordering chunks. The
    # post-check would then reject the result, so wire->unwire round
    # trips on ``env:``-before-``with:`` workflows would silently break.
    owned_ranges.sort(key=lambda r: r[0])

    # For each owned mapping, scan its child lines at the canonical indent
    # and drop those whose key matches an owned name. Rebuild the block
    # by stitching together unmodified sibling regions and the cleaned
    # child region.
    pieces: list[str] = []
    last = 0
    for block_start, block_end, child_indent, _label in owned_ranges:
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
            if not isinstance(uses, str) or not _is_action_uses(uses):
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
            # ``env:`` is required. A previous version accepted a missing
            # ``env:`` (because ``step.get("env")`` is ``None`` when the
            # step has no ``env:`` mapping), which let a nested ``env:``
            # inside a ``prompt: |`` block scalar -- parsed as a sibling
            # string, not the step's ``env:`` mapping -- pass the check.
            # Wire is required to create an ``env:`` block when none exists
            # (see ``_do``), so requiring it here is sound.
            env_map = step.get("env")
            if env_map is None:
                unwired.append(f"{step_id}: missing env: mapping")
            elif not isinstance(env_map, dict):
                unwired.append(
                    f"{step_id}: env: is {env_map!r} (not a mapping); "
                    "cannot carry MERGECRAFT_TRACING_PROJECT"
                )
            else:
                for key in REQUIRED_ENV_KEYS:
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
            if not isinstance(uses, str) or not _is_action_uses(uses):
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
    region: str | None = None,
) -> WiringChange:
    """Insert the owned keys into every selected ``uses:`` step in ``workflow_path``.

    When *region* is ``"us"`` / ``"eu"``, an additional
    ``MERGECRAFT_TRACING_REGION`` entry is written into the step's ``env:``
    mapping. Logfire serves region-specific OTLP ingest hosts
    (``logfire-us.pydantic.dev`` / ``logfire-eu.pydantic.dev``) and the
    resolver defaults to ``us``; an EU write token therefore needs this key or
    its spans are posted to the wrong host. ``None`` (the default) leaves the
    key alone, preserving the pre-existing wiring shape.
    """
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
    if region is not None:
        normalised = region.strip().lower()
        if normalised not in {"us", "eu"}:
            raise LogfireWorkflowError(f"region must be 'us' or 'eu' (got {region!r})")
        env_canonical.append(("MERGECRAFT_TRACING_REGION", normalised))

    def _do(block: str, step_indent: int) -> tuple[str, bool]:
        # Order matters: insert ``with:`` keys first so an existing ``env:``
        # block's byte offsets used by the second call haven't been perturbed.
        # ``step_indent`` scopes the ``with:`` / ``env:`` search to the step's
        # body indent so a literal ``env:`` inside a ``prompt: |`` block
        # scalar can't be mistaken for the step's real ``env:`` mapping.
        block2, mod_with = _insert_owned_keys_into_block(
            block,
            key="with",
            canonical=with_canonical,
            env_style=False,
            force=force,
            at_indent=step_indent,
        )
        # Every mergeCraft action input is ``required: false`` in
        # ``action.yml``, so a valid step may omit ``with:`` entirely (the
        # README's Example 1 -- auto-review every PR -- defines only
        # ``env:`` on the step). When that's the case the prior ``with:``
        # insert is a no-op *and* there's no existing ``with:`` block to
        # extend, so we must create one -- symmetric with the ``env:``
        # branch below -- or the post-mutation semantic check rejects the
        # result (``with: is None``).
        if not mod_with and _find_mapping_block(block2, "with", at_indent=step_indent) is None:
            block2 = _create_with_block(block2, with_canonical, at_indent=step_indent)
            mod_with = True
        block3, mod_env = _insert_owned_keys_into_block(
            block2,
            key="env",
            canonical=env_canonical,
            env_style=True,
            force=force,
            at_indent=step_indent,
        )
        if not mod_env and _find_mapping_block(block2, "env", at_indent=step_indent) is None:
            # ``env:`` block is genuinely absent -- create one immediately
            # after the ``with:`` block (or after ``uses:`` if no ``with:``).
            block3 = _create_env_block(block2, env_canonical, at_indent=step_indent)
            mod_env = True
        return block3, mod_with or mod_env

    return _mutate_steps(
        text,
        step_selector=step_selector,
        mutate_one=_do,
        post_mutation_check=_assert_wired_semantics,
    )


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


__all__ = [
    "DEFAULT_WORKFLOW_RELATIVE_PATH",
    "OWNED_ENV_KEYS",
    "OWNED_WITH_KEYS",
    "REQUIRED_ENV_KEYS",
    "LogfireWorkflowError",
    "WiringChange",
    "apply_logfire_wiring",
    "remove_logfire_wiring",
    "render_workflow_diff",
]
