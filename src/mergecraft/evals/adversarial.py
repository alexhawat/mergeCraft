"""Adversarial prompt-injection corpus and fence harness (EV3).

The injection fence mechanics shipped in W4 (:mod:`mergecraft.utils.fence` —
nonce-bound ``render_untrusted`` / ``fence_unless_trusted`` with delimiter
neutralization) and are unit-tested there. This module is the **corpus-level
proof**: one hostile case per attack vector lives under
``evals/cases/adversarial/`` as JSON, and :func:`check_fence` runs every case
through the real fence path on every suite run, so a future fence regression
is caught here rather than in production.

Global convention 4 applies with full force: the harness **reuses** the W4
fence — it never re-implements wrapping, neutralization, or trust-tier
short-circuiting.

Corpus layout: one JSON file per hostile shape under
:data:`DEFAULT_ADVERSARIAL_CORPUS_DIR`. The bank's ``list_cases`` reads only
top-level ``*.md`` files, so the subdirectory cannot leak into structural
replay. Decision-bearing vectors (``poisoned_context``,
``misleading_tests``) record ``expected_decision == "block"`` as
corpus-claimed truth — the structural suite asserts the record stays
non-approval-shaped.

Like the rest of ``mergecraft.evals``, this module is a pure core: it reads
files only when handed a path, has no ``os.environ`` reads, and performs no
I/O at import time (§W11.6).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.classify.change_classifier import classify_change
from mergecraft.utils.fence import (
    SAFETY_NOTE,
    TRUSTED_ASSOCIATIONS,
    Fence,
    fence_unless_trusted,
)

if TYPE_CHECKING:
    from mergecraft.classify.blast_radius import ChangeSet

#: Default on-disk location of the adversarial corpus — one JSON case per
#: hostile shape. Deliberately a *subdirectory* of the eval bank so the
#: bank's top-level ``*.md`` scan never picks these up.
DEFAULT_ADVERSARIAL_CORPUS_DIR: Final[Path] = Path("evals/cases/adversarial")

#: The attack-vector vocabulary. Every vector must carry at least one corpus
#: case; discovery fails loudly otherwise (an empty corpus is a failure,
#: never a vacuous pass).
ADVERSARIAL_VECTORS: Final[frozenset[str]] = frozenset(
    {
        "pr_body",
        "review_comment",
        "commit_message",
        "poisoned_context",
        "misleading_tests",
        "generated_code",
    }
)

AdversarialVector = Literal[
    "pr_body",
    "review_comment",
    "commit_message",
    "poisoned_context",
    "misleading_tests",
    "generated_code",
]

#: How a case's content is routed: human-shaped text is *reviewed* through
#: the fence; generated code is *classified* by the change classifier instead
#: of being reviewed as human-authored.
HandledAs = Literal["reviewed", "classified"]

_CASE_FILE_SUFFIX: Final[str] = ".json"

# Matches the real fence's delimiter/nonce shapes so the harness can verify
# the *body* of a rendered block carries none of them.
_DELIMITER_OPEN_RE: Final = re.compile(r"<<<UNTRUSTED-MERGECRAFT-CONTENT\b")
_DELIMITER_CLOSE_RE: Final = re.compile(r"<<<END-UNTRUSTED-MERGECRAFT-CONTENT\b")
_NONCE_TOKEN_RE: Final = re.compile(r"nonce=[0-9a-f]{16}")


class AdversarialCase(BaseModel):
    """One hostile corpus case loaded from ``evals/cases/adversarial/``.

    ``payload`` is the hostile field text — instruction-shaped content,
    typically including a forged closing-delimiter attempt. ``legit_marker``
    is the legitimate content (e.g. the seeded bug's diff line) that must
    survive fencing intact; empty for vectors with no legit payload. Every
    corpus case is untrusted-authored by construction.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    vector: AdversarialVector
    payload: str
    author: str
    author_association: str
    legit_marker: str = ""
    expected_decision: str = ""
    #: Paths the change touches — used by the generated-code vector so the
    #: classifier (not the reviewer path) routes the case.
    changed_paths: list[str] = Field(default_factory=list)


class FenceCheck(BaseModel):
    """Outcome of running one adversarial case through the real fence."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    #: The payload was rendered inside the nonce-bound untrusted block.
    fenced: bool
    #: The payload cannot terminate its own fence early — no delimiter shape
    #: or ``nonce=<16hex>`` token survives neutralization inside the body.
    forged_delimiters_neutralized: bool
    #: The case's ``legit_marker`` survived fencing verbatim.
    legit_content_preserved: bool
    handled_as: HandledAs


def _load_case(path: Path) -> AdversarialCase:
    return AdversarialCase.model_validate(json.loads(path.read_text(encoding="utf-8")))


def discover_adversarial_cases(
    corpus_dir: Path = DEFAULT_ADVERSARIAL_CORPUS_DIR,
) -> list[AdversarialCase]:
    """Load every adversarial case under ``corpus_dir``, sorted by filename.

    Fails loudly when the corpus is missing or any attack vector carries no
    case — a silently incomplete corpus is exactly the regression this suite
    exists to catch.

    Raises:
        FileNotFoundError: The corpus directory does not exist.
        ValueError: A case file failed validation, or some attack vector has
            no case.
    """
    if not corpus_dir.is_dir():
        msg = f"adversarial corpus directory does not exist: {corpus_dir}"
        raise FileNotFoundError(msg)
    cases = [_load_case(path) for path in sorted(corpus_dir.glob(f"*{_CASE_FILE_SUFFIX}"))]
    seen = {case.vector for case in cases}
    missing = sorted(ADVERSARIAL_VECTORS - seen)
    if missing:
        msg = f"adversarial corpus {corpus_dir} carries no case for vector(s): {missing}"
        raise ValueError(msg)
    return cases


def _field_text(case: AdversarialCase) -> str:
    """The full submitted field text: legitimate content plus hostile payload."""
    if case.legit_marker:
        return f"{case.legit_marker}\n\n{case.payload}"
    return case.payload


def _is_classified_generated_code(case: AdversarialCase) -> bool:
    """True when the change classifier routes every path as generated."""
    if not case.changed_paths:
        return False
    change: ChangeSet = {"changed_paths": list(case.changed_paths), "diff_stats": {}}
    classification = classify_change(change)
    generated = classification.change_map["generated_paths"]
    return isinstance(generated, list) and len(generated) == len(case.changed_paths)


def check_fence(case: AdversarialCase, *, fence: Fence | None = None) -> FenceCheck:
    """Run one adversarial case through the real W4 fence mechanics.

    The case's field text goes through ``fence_unless_trusted`` — the same
    call-site helper ``resolve_instructions()`` uses — with a per-check
    :class:`~mergecraft.utils.fence.Fence` nonce. The returned
    :class:`FenceCheck` reports whether the payload landed inside the
    nonce-bound block, whether forged delimiters were neutralized, whether
    legitimate content survived, and how the case is routed (generated code
    is *classified*, everything else is *reviewed*).
    """
    nonce = (fence or Fence()).nonce
    rendered = fence_unless_trusted(
        _field_text(case),
        author=case.author,
        author_association=case.author_association,
        tier="trusted" if case.author_association in TRUSTED_ASSOCIATIONS else "untrusted",
        label=case.vector,
        nonce=nonce,
    )
    header = f"<<<UNTRUSTED-MERGECRAFT-CONTENT nonce={nonce} "
    footer = f"<<<END-UNTRUSTED-MERGECRAFT-CONTENT nonce={nonce}>>>"
    lines = rendered.splitlines()
    fenced = (
        rendered != _field_text(case)
        and lines[0].startswith(header)
        and lines[-1] == footer
        and SAFETY_NOTE in rendered
    )
    body = "\n".join(lines[1:-1]) if fenced else ""
    neutralized = not (
        _DELIMITER_OPEN_RE.search(body)
        or _DELIMITER_CLOSE_RE.search(body)
        or _NONCE_TOKEN_RE.search(body)
    )
    handled_as: HandledAs = (
        "classified"
        if case.vector == "generated_code" and _is_classified_generated_code(case)
        else "reviewed"
    )
    return FenceCheck(
        case_id=case.case_id,
        fenced=fenced,
        forged_delimiters_neutralized=fenced and neutralized,
        legit_content_preserved=not case.legit_marker or case.legit_marker in rendered,
        handled_as=handled_as,
    )


__all__ = [
    "ADVERSARIAL_VECTORS",
    "DEFAULT_ADVERSARIAL_CORPUS_DIR",
    "AdversarialCase",
    "AdversarialVector",
    "FenceCheck",
    "HandledAs",
    "check_fence",
    "discover_adversarial_cases",
]
