# Cross-file dependencies between wave plans (operator tracker)

This file tracks **shared types / surfaces / modules** that two or more
operator-authored wave plans touch. Each row pins the *public* surface
the second plan depends on, so the rebaser does not regress the first
plan's contract when the second plan's wave lands.

This is an in-repo tracker (committed) — operator-facing, not
GitHub-tracked. Wave plans themselves remain in
`.ignorelocal/waves/` (gitignored, per-batch).

## Conventions

- One row per shared surface.
- The **owner** column names the wave plan that wrote the canonical
  contract first; the **consumer** column names the plan that must
  reuse (not reimplement) it.
- The **public API** column captures the import path + the type or
  function name + field names, verbatim, so the consumer plan can
  pick it up without re-reading the owner's source.
- When both plans are merged, the row stays here as a historical
  reference for future readers; do not delete it.

---

## Security Batch C (#74) → merge-evidence W11 (#51)

| Field | Value |
|-------|-------|
| Owner | `wave/sec-c-learnings-trust` — `feat(learnings): provenance-gate and quarantine new entries (#74)`, commit `cae4e98`. Wave plan: `.ignorelocal/waves/issues-security-trust-boundary-wave-plan.md` C-Final. |
| Consumer | merge-evidence W11 — Failure Memory and Eval Bank (#51). Wave plan: `.ignorelocal/waves/issues-merge-evidence-gating-wave-plan.md` W11. |
| Surface | `LearningProvenance` Pydantic record on every persisted learning entry. |
| Why this matters | #51's eval bank is a second durable store; #74's issue body names it explicitly: "any durable memory store needs the same provenance discipline". The merge-evidence plan reuses this type rather than defining a second one. |

### Public API surface (verbatim)

- **Module:** `src/mergecraft/utils/learnings.py`
- **Class:** `LearningProvenance`
- **Pydantic config:** `model_config = ConfigDict(extra="forbid")`
- **Fields:**
  | Field | Type | Notes |
  |-------|------|-------|
  | `run_id` | `str` | `Field(min_length=1)` — non-empty |
  | `pr_number` | `int \| None` | PR number, or `None` for non-PR runs |
  | `source_field` | `str` | `Field(min_length=1)` — which field this entry was derived from |
  | `author_login` | `str` | `Field(min_length=1)` |
  | `author_association` | `str \| None` | GitHub `author_association`; `None` when not available |
  | `trust_tier` | `Literal["trusted", "untrusted"]` | from `analyzers.trust.derive_trust_tier` |
  | `timestamp` | `datetime` | rendered as `YYYY-MM-DDTHH:MM:SSZ` UTC |
- **Helpers on the module:**
  - `LearningProvenance.render_comment() -> str` — produces a single
    `<!-- provenance: run_id=… pr_number=… source_field=… author_login=… author_association=… trust_tier=… timestamp=… -->`
    HTML comment line for the wire format.
  - `parse_provenance_comment(line: str) -> LearningProvenance | None`
    — strict parser that rejects forged extra fields, bad timestamps,
    invalid `trust_tier` values, and empty `run_id`. Use this on the
    read path; do **not** parse the comment line yourself.
  - `is_trusted_association(value: str | None) -> bool` — gates on
    `{"OWNER", "MEMBER", "COLLABORATOR"}`. Mirrors
    `mergecraft.utils.fence.TRUSTED_ASSOCIATIONS`.
  - `TRUSTED_AUTHOR_ASSOCIATIONS: frozenset[str]` — the canonical
    trusted-author set.
  - `route_learnings_for_persist(*, current, seed, provenance, autopromote)`
    — the persistence router. Promotion into `## Active` is only
    allowed when `is_trusted_association(provenance.author_association)`
    **and** the caller's `autopromote=True`. Non-maintainer entries
    are always routed into `## Staging`.
  - `list_active_entries(text: str)` /
    `list_staging_entries(text: str)` — list parsed entries with their
    provenance records (for the CLI influence listing).
  - `split_learnings_by_section(current: str, seed: str)` — line-level
    diff helper returning `(seed_part, new_part)`.

### Wire format

Inline HTML comment block placed immediately above each entry's
heading. Round-trips through `parse_learnings_headings` without a
separate parser. Example:

```
<!-- provenance: run_id=123 pr_number=42 source_field=learnings_md author_login=alice author_association=MEMBER trust_tier=trusted timestamp=2026-08-08T12:00:00Z -->

## Maintainer review outcome — auth module needs explicit allowlist
- …entry body…
```

### Import path

```python
from mergecraft.utils.learnings import (
    LearningProvenance,
    TRUSTED_AUTHOR_ASSOCIATIONS,
    is_trusted_association,
    parse_provenance_comment,
    route_learnings_for_persist,
    list_active_entries,
    list_staging_entries,
)
```

### Contract assertions (do not regress)

- `extra="forbid"` on `LearningProvenance` makes any field rename
  breaking; additive changes only.
- `parse_provenance_comment` is strict (rejects forged / malformed
  inputs); the W5 RED suite proves the wire format cannot be smuggled
  into via untrusted text.
- `route_learnings_for_persist` is the structural gate — the
  `_LEARNINGS_PROVENANCE_NOTE` in `agents/post_run.py` is the
  **soft constraint that backs** the structural gate by telling the
  model not to author learnings from untrusted input. The eval bank
  must keep the structural gate at the persistence layer, not rely on
  prompt-level rules.

### Cross-file collision policy

If the merge-evidence W11 needs to extend `LearningProvenance`
(additively, not in-place), the extension must land as a sibling type
(`MergeEvidenceProvenance` or similar) that *embeds* `LearningProvenance`
rather than re-declaring its fields. The strict `extra="forbid"`
config makes any rename of the existing fields breaking for both
plans.

### References

- [#74 — learnings provenance](https://github.com/alexhawat/mergeCraft/issues/74)
- [#51 — Failure Memory and Eval Bank](https://github.com/alexhawat/mergeCraft/issues/51)
- PR #86 — Batch C draft (the breaking-default convention; gated on the
  merge-evidence companion PR)
- W6 commit: `cae4e98` — `LearningProvenance`, `route_learnings_for_persist`
- Wave plan: `.ignorelocal/waves/issues-security-trust-boundary-wave-plan.md`
  — Cross-file collisions section names this row.
